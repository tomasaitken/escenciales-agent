import asyncio
import os
import logging
import hashlib
import re
import time
import unicodedata
from contextlib import asynccontextmanager
from contextlib import suppress
from dataclasses import replace
from fastapi import BackgroundTasks, FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv

from agent.admin import router as admin_router
from agent.audio import transcribir_audio
from agent.brain import (
    cargar_business_config,
    generar_respuesta,
    identificar_producto_desde_imagen,
    obtener_mensaje_error,
    obtener_mensaje_fallback,
)
from agent.handoff import detectar_handoff, mensaje_handoff, respuesta_promete_handoff
from agent.legal import router as legal_router
from agent.memory import (
    cancelar_seguimientos_compra,
    conversacion_pausada,
    crear_handoff,
    finalizar_seguimiento_compra,
    inicializar_db,
    guardar_mensaje,
    obtener_historial,
    programar_seguimiento_compra,
    purgar_datos_antiguos,
    reclamar_seguimientos_vencidos,
    registrar_evento_si_nuevo,
    seguimiento_compra_activo,
)
from agent.notifier import notificar_handoff
from agent.providers import obtener_proveedor

load_dotenv()

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
log_level = logging.DEBUG if ENVIRONMENT == "development" else logging.INFO
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("escenciales")
logger.setLevel(log_level)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("aiosqlite").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy").setLevel(logging.WARNING)

proveedor = obtener_proveedor()
PORT = int(os.getenv("PORT", 8000))

_fragmentos_pendientes: dict[str, list] = {}
_version_fragmentos: dict[str, int] = {}
_productos_anuncio_cache: dict[str, str] = {}
_mensajes_recientes: dict[str, float] = {}


def _respuestas_habilitadas() -> bool:
    """Interruptor operativo global; mantiene webhooks activos sin contestar."""
    valor = os.getenv("AGENT_RESPONSES_ENABLED", "true").strip().lower()
    return valor not in {"0", "false", "no", "off", "disabled", "paused"}


def _es_repetido_reciente(msg, texto: str, ventana_segundos: float = 60.0) -> bool:
    """Evita responder dos veces cuando Meta repite el mismo texto con otro ID."""
    ahora = time.monotonic()
    texto_normalizado = re.sub(r"\s+", " ", _normalizar(texto)).strip()
    clave = (
        f"{msg.canal}:{msg.telefono}:{msg.contexto_producto or ''}:"
        f"{texto_normalizado}"
    )
    anterior = _mensajes_recientes.get(clave)
    _mensajes_recientes[clave] = ahora

    if len(_mensajes_recientes) > 1000:
        limite = ahora - max(ventana_segundos, 60.0)
        for item, instante in list(_mensajes_recientes.items()):
            if instante < limite:
                _mensajes_recientes.pop(item, None)
    return anterior is not None and ahora - anterior <= ventana_segundos


def _texto_con_contexto_anuncio(texto: str, producto: str | None) -> str:
    if not producto:
        return texto
    return f"[Producto identificado desde el anuncio de Meta: {producto}]\n{texto}"


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(
        caracter for caracter in texto if not unicodedata.combining(caracter)
    ).lower()


def _producto_desde_texto(texto: str) -> str | None:
    texto = _normalizar(texto)
    patrones = (
        (r"\b(antena|tv\s*cable|television|canales?)\b", "Antena Digital Full HD 4K"),
        (r"\b(ducha|cabezal|presion\s+de\s+agua)\b", "Cabezal de ducha"),
        (r"\b(electroestimulador|tens|electrodos?)\b", "Electroestimulador TENS"),
    )
    return next(
        (producto for patron, producto in patrones if re.search(patron, texto)),
        None,
    )


def _producto_de_conversacion(
    contexto_producto: str | None,
    texto: str,
    historial: list[dict],
    nuevo_contexto_anuncio: bool = False,
) -> str | None:
    if contexto_producto:
        return contexto_producto
    producto = _producto_desde_texto(texto)
    if producto:
        return producto
    # Un clic nuevo en un anuncio abre un contexto comercial nuevo. Si Meta y la
    # miniatura no permiten identificarlo, nunca heredar el producto de mensajes
    # anteriores de ese mismo contacto.
    if nuevo_contexto_anuncio:
        return None
    for mensaje in reversed(historial):
        producto = _producto_desde_texto(str(mensaje.get("content", "")))
        if producto:
            return producto
    return None


def _respuesta_ubicacion_comercial(
    texto: str,
    producto: str | None,
) -> str | None:
    """Evita respuestas secas o distintas por canal ante preguntas de ubicación."""
    normalizado = _normalizar(texto)
    patrones = (
        r"\bdonde\s+(estan|se ubican|quedan|queda|esta)\b",
        r"\b(ubicacion|ubicados|direccion|tienda fisica|local fisico)\b",
        r"\bde que (comuna|ciudad|parte) son\b",
        r"\bde donde son\b",
        r"\bson de (santiago|que comuna|que ciudad)\b",
        r"\b(tienen|hay) (tienda|local)\b",
    )
    if not any(re.search(patron, normalizado) for patron in patrones):
        return None

    preguntas = {
        "Antena Digital Full HD 4K": "¿Qué te gustaría saber sobre la antena?",
        "Cabezal de ducha": "¿Qué te gustaría saber sobre la ducha?",
        "Electroestimulador TENS": (
            "¿Qué te gustaría saber sobre el electroestimulador TENS?"
        ),
    }
    cierre = preguntas.get(producto, "¿Con cuál producto te puedo ayudar?")
    return (
        "Somos una tienda online ubicada en Santiago de Chile 😊 Hacemos envíos "
        "gratis a todo Chile y el pago es contraentrega: pagas cuando recibes "
        f"el producto. {cierre}"
    )


def _url_compra(producto: str | None) -> str | None:
    if not producto:
        return None
    claves = {
        "Antena Digital Full HD 4K": "antena digital full hd 4k",
        "Cabezal de ducha": "ducha masajeadora spa pro",
        "Electroestimulador TENS": "electroestimulador tens",
    }
    clave = claves.get(producto)
    if not clave:
        return None
    for item in cargar_business_config().get("catalogo", []):
        nombres = " ".join(
            str(item.get(campo, ""))
            for campo in ("nombre", "nombre_comercial")
        )
        if clave in _normalizar(nombres):
            return item.get("url_compra")
    return None


def _mensaje_compra(producto: str | None, historial: list[dict]) -> str | None:
    url = _url_compra(producto)
    if not url or any(url in str(item.get("content", "")) for item in historial):
        return None
    pronombre = "lo" if producto == "Electroestimulador TENS" else "la"
    return (
        f"🛒 Cuando quieras comprar{pronombre}, puedes hacerlo aquí:\n{url}\n\n"
        'Pulsa "PAGA Contra ENTREGA" y completa el formulario. Si se te '
        "complica, dime y una persona del equipo sigue contigo por este mismo chat."
    )


def _debe_enviar_enlace(texto: str, historial: list[dict]) -> bool:
    """Entrega el checkout solo cuando el cliente muestra intención de compra."""
    normalizado = _normalizar(texto)
    patrones = (
        r"\b(como|donde)\s+(?:lo\s+|la\s+)?(compro|pido|encargo)\b",
        r"\bcomo\s+(?:hago|realizo|ingreso)\b.{0,25}\b(pedido|compra)\b",
        r"\b(quiero|kiero|qro|voy a|deseo)\b.{0,25}\b(comprar|pedir|encargar)\b",
        r"\b(lo|la|me lo|me la)\s+(llevo|quedo|compro)\b",
        r"\b(manda|mandame|pasa|pasame|envia|enviame)\w*\b.{0,25}\b(link|enlace)\b",
        r"\b(link|enlace)\b.{0,25}\b(comprar|compra|pedido|pagar)\b",
        r"\b(hacer|realizar|ingresar)\b.{0,20}\b(el\s+)?pedido\b",
    )
    if any(re.search(patron, normalizado) for patron in patrones):
        return True

    confirmacion_breve = re.fullmatch(
        r"\s*(si|sipo|sip|ya|ok|okay|dale|bueno|quiero)\s*[.!?]*\s*",
        normalizado,
    )
    if not confirmacion_breve:
        return False
    ultima_respuesta = next(
        (
            _normalizar(str(item.get("content", "")))
            for item in reversed(historial)
            if item.get("role") == "assistant"
        ),
        "",
    )
    return bool(
        re.search(
            r"\b(compr\w*|pedido|formulario|link|enlace|paga contra entrega)\b",
            ultima_respuesta,
        )
        and "?" in ultima_respuesta
    )


def _seguimientos_habilitados() -> bool:
    return os.getenv("PURCHASE_FOLLOWUP_ENABLED", "true").strip().lower() in {
        "1", "true", "yes", "si", "sí", "on",
    }


def _mensaje_seguimiento_compra(producto: str) -> str:
    nombres = {
        "Antena Digital Full HD 4K": "la antena",
        "Cabezal de ducha": "la ducha",
        "Electroestimulador TENS": "el electroestimulador TENS",
    }
    nombre = nombres.get(producto, "el producto")
    return (
        f"¿Pudiste avanzar con la compra de {nombre}? 😊 Si necesitas ayuda "
        "con el formulario o prefieres que una persona del equipo te ayude, "
        "dime y seguimos por este mismo chat."
    )


async def _procesar_seguimientos_vencidos() -> None:
    for seguimiento in await reclamar_seguimientos_vencidos():
        try:
            conversacion_id = seguimiento["conversacion_id"]
            if await conversacion_pausada(conversacion_id):
                await cancelar_seguimientos_compra(conversacion_id)
                continue
            if not await seguimiento_compra_activo(seguimiento["id"]):
                continue
            mensaje = _mensaje_seguimiento_compra(seguimiento["producto"])
            enviado = await proveedor.enviar_mensaje(
                seguimiento["contacto"],
                mensaje,
                canal=seguimiento["canal"],
            )
            if enviado:
                await guardar_mensaje(conversacion_id, "assistant", mensaje)
            await finalizar_seguimiento_compra(seguimiento["id"], enviado)
        except Exception:
            logger.exception("Error procesando seguimiento de compra")
            await finalizar_seguimiento_compra(seguimiento["id"], False)


async def _bucle_seguimientos_compra() -> None:
    intervalo = max(2.0, float(os.getenv("PURCHASE_FOLLOWUP_POLL_SECONDS", "10")))
    while True:
        await _procesar_seguimientos_vencidos()
        await asyncio.sleep(intervalo)


async def _resolver_producto_visual_anuncio(msg):
    if msg.es_propio or not msg.contexto_media_url:
        return msg
    clave = msg.contexto_anuncio_id or hashlib.sha256(
        msg.contexto_media_url.encode("utf-8")
    ).hexdigest()
    producto_visual = _productos_anuncio_cache.get(clave)
    if producto_visual:
        if msg.contexto_producto and msg.contexto_producto != producto_visual:
            logger.warning("Conflicto entre metadatos y miniatura de anuncio")
            return replace(msg, contexto_producto=None)
        return replace(msg, contexto_producto=producto_visual)
    try:
        contenido, mime_type = await proveedor.obtener_imagen_anuncio(msg)
        identificador = hashlib.sha256(msg.telefono.encode()).hexdigest()[:32]
        producto_visual = await identificar_producto_desde_imagen(
            contenido,
            mime_type,
            safety_identifier=f"esc_{identificador}",
        )
    except Exception as exc:
        logger.warning(
            "No se pudo leer miniatura de anuncio tipo=%s",
            type(exc).__name__,
        )
        return msg
    if not producto_visual:
        logger.info("Miniatura de anuncio sin producto reconocible")
        return msg
    if msg.contexto_producto and msg.contexto_producto != producto_visual:
        logger.warning("Conflicto entre metadatos y miniatura de anuncio")
        return replace(msg, contexto_producto=None)
    if len(_productos_anuncio_cache) >= 100:
        _productos_anuncio_cache.pop(next(iter(_productos_anuncio_cache)))
    _productos_anuncio_cache[clave] = producto_visual
    logger.info("Producto de anuncio identificado visualmente: %s", producto_visual)
    return replace(msg, contexto_producto=producto_visual)


async def _esperar_fragmentos(msg):
    """Agrupa textos consecutivos del mismo contacto antes de responder."""
    # Meta puede entregar mensajes enviados seguidos con varios segundos de
    # diferencia. La espera se reinicia con cada fragmento nuevo.
    espera = max(0.0, float(os.getenv("MESSAGE_DEBOUNCE_SECONDS", "8")))
    if espera == 0 or msg.es_propio or msg.tipo != "text":
        return [msg]

    clave = f"{msg.canal}:{msg.telefono}"
    lote = _fragmentos_pendientes.setdefault(clave, [])
    lote.append(msg)
    version = _version_fragmentos.get(clave, 0) + 1
    _version_fragmentos[clave] = version

    await asyncio.sleep(espera)
    if _version_fragmentos.get(clave) != version:
        return []

    _version_fragmentos.pop(clave, None)
    return _fragmentos_pendientes.pop(clave, [])


@asynccontextmanager
async def lifespan(app: FastAPI):
    if ENVIRONMENT == "production":
        requeridas = [
            "OPENAI_API_KEY", "ADMIN_PASSWORD", "META_APP_ID", "META_APP_SECRET",
            "META_ACCESS_TOKEN", "META_PAGE_ACCESS_TOKEN", "WHATSAPP_VERIFY_TOKEN",
            "META_INSTAGRAM_ACCESS_TOKEN", "META_INSTAGRAM_ACCOUNT_ID",
            "META_INSTAGRAM_APP_ID",
            "META_GRAPH_API_VERSION", "WHATSAPP_PHONE_NUMBER_ID",
            "WHATSAPP_BUSINESS_ACCOUNT_ID", "IG_PAGE_ID", "FB_PAGE_ID",
        ]
        faltantes = [nombre for nombre in requeridas if not os.getenv(nombre)]
        if faltantes:
            raise RuntimeError(
                "Faltan variables obligatorias de producción: " + ", ".join(faltantes)
            )
        if len(os.environ["WHATSAPP_VERIFY_TOKEN"]) < 32:
            raise RuntimeError("WHATSAPP_VERIFY_TOKEN debe tener al menos 32 caracteres")
        if len(os.environ["ADMIN_PASSWORD"]) < 16:
            raise RuntimeError("ADMIN_PASSWORD debe tener al menos 16 caracteres")
        if DATABASE_URL := os.getenv("DATABASE_URL", ""):
            if DATABASE_URL.startswith("sqlite"):
                raise RuntimeError("Producción requiere PostgreSQL; SQLite no está permitido")
        else:
            raise RuntimeError("DATABASE_URL es obligatoria en producción")
    await inicializar_db()
    await purgar_datos_antiguos(int(os.getenv("DATA_RETENTION_DAYS", "90")))
    logger.info("=" * 50)
    logger.info("  Escenciales — Agente comercial omnicanal")
    logger.info(f"  Proveedor: {proveedor.__class__.__name__}")
    logger.info(f"  Puerto: {PORT}")
    logger.info(f"  Entorno: {ENVIRONMENT}")
    logger.info("=" * 50)
    tarea_seguimientos = None
    if _seguimientos_habilitados():
        tarea_seguimientos = asyncio.create_task(_bucle_seguimientos_compra())
        logger.info(
            "Seguimiento de compra activo demora_min=%s",
            os.getenv("PURCHASE_FOLLOWUP_MINUTES", "15"),
        )
    try:
        yield
    finally:
        if tarea_seguimientos:
            tarea_seguimientos.cancel()
            with suppress(asyncio.CancelledError):
                await tarea_seguimientos


app = FastAPI(
    title="Escenciales — Agente comercial omnicanal",
    version="3.6.1",
    lifespan=lifespan
)
app.include_router(admin_router)
app.include_router(legal_router)


@app.get("/")
async def health_check():
    return {
        "status": "ok",
        "agent": "Escenciales",
        "version": "3.6.1",
        "responses_enabled": _respuestas_habilitadas(),
    }


@app.get("/webhook")
async def webhook_verificacion(request: Request):
    resultado = await proveedor.validar_webhook(request)
    if resultado is not None:
        return PlainTextResponse(str(resultado))
    return {"status": "ok"}


async def procesar_mensajes(mensajes):
    if not _respuestas_habilitadas():
        logger.warning(
            "Agente pausado globalmente; %s mensaje(s) recibido(s) sin respuesta",
            len(mensajes),
        )
        return
    if len(mensajes) > 1:
        await asyncio.gather(*(procesar_mensajes([msg]) for msg in mensajes))
        return
    for msg in mensajes:
        try:
            msg = await _resolver_producto_visual_anuncio(msg)
            evento_pre_registrado = False
            if not msg.es_propio and msg.tipo == "text":
                lote = await _esperar_fragmentos(msg)
                if not lote:
                    continue
                partes_nuevas = []
                for parte in lote:
                    if await registrar_evento_si_nuevo(parte.mensaje_id):
                        partes_nuevas.append(parte)
                if not partes_nuevas:
                    logger.info("Webhook duplicado ignorado")
                    continue
                texto_unido = "\n".join(
                    parte.texto.strip() for parte in partes_nuevas if parte.texto.strip()
                )
                contexto_producto = next(
                    (
                        parte.contexto_producto
                        for parte in partes_nuevas
                        if parte.contexto_producto
                    ),
                    None,
                )
                contexto_media_url = next(
                    (
                        parte.contexto_media_url
                        for parte in partes_nuevas
                        if parte.contexto_media_url
                    ),
                    None,
                )
                contexto_anuncio_id = next(
                    (
                        parte.contexto_anuncio_id
                        for parte in partes_nuevas
                        if parte.contexto_anuncio_id
                    ),
                    None,
                )
                msg = replace(
                    partes_nuevas[-1],
                    texto=texto_unido,
                    mensaje_id="",
                    contexto_producto=contexto_producto,
                    contexto_media_url=contexto_media_url,
                    contexto_anuncio_id=contexto_anuncio_id,
                )
                evento_pre_registrado = True

            if msg.es_propio:
                if not msg.telefono:
                    continue
                if not await registrar_evento_si_nuevo(msg.mensaje_id):
                    logger.info("Webhook de operador duplicado ignorado")
                    continue

                conversacion_id = f"{msg.canal}:{msg.telefono}"
                await cancelar_seguimientos_compra(conversacion_id)
                texto_manual = msg.texto.strip() or "[Respuesta manual del equipo]"
                await guardar_mensaje(conversacion_id, "assistant", texto_manual)
                await crear_handoff(
                    conversacion_id,
                    msg.canal,
                    msg.telefono,
                    "operador_manual",
                    texto_manual,
                )
                contacto_hash = hashlib.sha256(msg.telefono.encode()).hexdigest()[:10]
                logger.info(
                    "Respuesta manual detectada; bot pausado contacto=%s",
                    contacto_hash,
                )
                continue
            if not evento_pre_registrado and not await registrar_evento_si_nuevo(msg.mensaje_id):
                logger.info("Webhook duplicado ignorado")
                continue

            hash_completo = hashlib.sha256(msg.telefono.encode()).hexdigest()
            contacto_hash = hash_completo[:10]
            logger.info("Mensaje entrante [%s] contacto=%s", msg.canal, contacto_hash)

            conversacion_id = f"{msg.canal}:{msg.telefono}"
            await cancelar_seguimientos_compra(conversacion_id)
            texto = msg.texto.strip()

            if msg.tipo == "audio":
                try:
                    contenido, mime_type = await proveedor.obtener_audio(msg)
                    texto = await transcribir_audio(contenido, mime_type)
                    texto_para_historial = f"[Audio transcrito] {texto}"
                except Exception as exc:
                    logger.error(
                        "No se pudo procesar audio contacto=%s tipo=%s",
                        contacto_hash,
                        type(exc).__name__,
                    )
                    texto_para_historial = "[Audio recibido; transcripción fallida]"
                    texto_para_historial = _texto_con_contexto_anuncio(
                        texto_para_historial, msg.contexto_producto
                    )
                    await guardar_mensaje(conversacion_id, "user", texto_para_historial)
                    if await conversacion_pausada(conversacion_id):
                        continue
                    respuesta = (
                        "No pude escuchar bien ese audio. Dejaré la conversación "
                        "pendiente para que una persona del equipo te ayude por aquí."
                    )
                    ticket = await crear_handoff(
                        conversacion_id, msg.canal, msg.telefono,
                        "audio_no_procesado", texto_para_historial,
                    )
                    await guardar_mensaje(conversacion_id, "assistant", respuesta)
                    await proveedor.enviar_mensaje(msg.telefono, respuesta, canal=msg.canal)
                    await notificar_handoff(ticket["id"], msg.canal, "audio_no_procesado")
                    continue
            elif msg.tipo == "image":
                texto_para_historial = "[Imagen recibida]"
                if texto:
                    texto_para_historial += f" {texto}"
                texto_para_historial = _texto_con_contexto_anuncio(
                    texto_para_historial, msg.contexto_producto
                )
                await guardar_mensaje(conversacion_id, "user", texto_para_historial)
                if await conversacion_pausada(conversacion_id):
                    logger.info("Imagen guardada en conversación pausada contacto=%s", contacto_hash)
                    continue
                respuesta = (
                    "Gracias, recibí la foto. La dejaré pendiente para que una persona "
                    "del equipo la revise y continúe contigo por aquí."
                )
                ticket = await crear_handoff(
                    conversacion_id, msg.canal, msg.telefono,
                    "imagen_para_revision", texto_para_historial,
                )
                await guardar_mensaje(conversacion_id, "assistant", respuesta)
                enviado = await proveedor.enviar_mensaje(
                    msg.telefono, respuesta, canal=msg.canal
                )
                if not enviado:
                    logger.error("No se pudo enviar handoff de imagen contacto=%s", contacto_hash)
                await notificar_handoff(ticket["id"], msg.canal, "imagen_para_revision")
                continue
            else:
                texto_para_historial = texto

            if not texto:
                continue

            if _es_repetido_reciente(msg, texto):
                logger.info(
                    "Mensaje semánticamente duplicado ignorado contacto=%s",
                    contacto_hash,
                )
                continue

            texto_para_historial = _texto_con_contexto_anuncio(
                texto_para_historial, msg.contexto_producto
            )
            texto_para_modelo = _texto_con_contexto_anuncio(
                texto, msg.contexto_producto
            )

            if await conversacion_pausada(conversacion_id):
                await guardar_mensaje(conversacion_id, "user", texto_para_historial)
                logger.info("Bot pausado; mensaje guardado contacto=%s", contacto_hash)
                continue

            motivo_handoff = detectar_handoff(texto)
            if motivo_handoff:
                respuesta = mensaje_handoff(motivo_handoff)
                await guardar_mensaje(conversacion_id, "user", texto_para_historial)
                await guardar_mensaje(conversacion_id, "assistant", respuesta)
                ticket = await crear_handoff(
                    conversacion_id,
                    msg.canal,
                    msg.telefono,
                    motivo_handoff,
                    texto_para_historial,
                )
                enviado = await proveedor.enviar_mensaje(
                    msg.telefono, respuesta, canal=msg.canal
                )
                if not enviado:
                    logger.error("No se pudo enviar handoff contacto=%s", contacto_hash)
                await notificar_handoff(ticket["id"], msg.canal, motivo_handoff)
                continue

            historial = await obtener_historial(conversacion_id)
            nuevo_contexto_anuncio = bool(
                msg.contexto_media_url or msg.contexto_anuncio_id
            )
            producto_conversacion = _producto_de_conversacion(
                msg.contexto_producto,
                texto,
                historial,
                nuevo_contexto_anuncio=nuevo_contexto_anuncio,
            )
            respuesta = _respuesta_ubicacion_comercial(
                texto,
                producto_conversacion,
            )
            if not respuesta:
                if nuevo_contexto_anuncio and not producto_conversacion:
                    respuesta = (
                        "Quiero asegurarme de darte la información correcta 😊 "
                        "¿El anuncio que viste es de la antena HD, el "
                        "electroestimulador TENS o la ducha?"
                    )
                else:
                    respuesta = await generar_respuesta(
                        texto_para_modelo,
                        historial,
                        canal=msg.canal,
                        safety_identifier=f"esc_{hash_completo[:32]}",
                    )

            ticket_modelo = None
            if respuesta_promete_handoff(respuesta):
                ticket_modelo = await crear_handoff(
                    conversacion_id,
                    msg.canal,
                    msg.telefono,
                    "escalamiento_modelo",
                    texto_para_historial,
                )
                logger.info("Promesa de apoyo humano convertida en handoff contacto=%s", contacto_hash)

            await guardar_mensaje(conversacion_id, "user", texto_para_historial)
            await guardar_mensaje(conversacion_id, "assistant", respuesta)

            enviado = await proveedor.enviar_mensaje(
                msg.telefono, respuesta, canal=msg.canal
            )
            if not enviado:
                logger.error("No se pudo enviar respuesta contacto=%s", contacto_hash)
            respuesta_tecnica = respuesta in {
                obtener_mensaje_error(),
                obtener_mensaje_fallback(),
            }
            if (
                enviado
                and not ticket_modelo
                and not respuesta_tecnica
                and _debe_enviar_enlace(texto, historial)
            ):
                mensaje_compra = _mensaje_compra(producto_conversacion, historial)
                if mensaje_compra:
                    enlace_enviado = await proveedor.enviar_mensaje(
                        msg.telefono, mensaje_compra, canal=msg.canal
                    )
                    if enlace_enviado:
                        await guardar_mensaje(
                            conversacion_id, "assistant", mensaje_compra
                        )
                        if _seguimientos_habilitados():
                            await programar_seguimiento_compra(
                                conversacion_id,
                                msg.canal,
                                msg.telefono,
                                producto_conversacion,
                                minutos=float(
                                    os.getenv("PURCHASE_FOLLOWUP_MINUTES", "15")
                                ),
                            )
                    else:
                        logger.error(
                            "No se pudo enviar enlace de compra contacto=%s",
                            contacto_hash,
                        )
            if ticket_modelo:
                await notificar_handoff(
                    ticket_modelo["id"], msg.canal, "escalamiento_modelo"
                )
        except Exception:
            logger.exception("Error procesando mensaje individual")


@app.post("/webhook")
async def webhook_handler(request: Request, background_tasks: BackgroundTasks):
    try:
        mensajes = await proveedor.parsear_webhook(request)
        background_tasks.add_task(procesar_mensajes, mensajes)
        return {"status": "accepted"}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error en webhook")
        raise HTTPException(status_code=500, detail="Error interno")
