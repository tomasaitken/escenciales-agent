import asyncio
import os
import logging
import hashlib
import re
import unicodedata
from contextlib import asynccontextmanager
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
    conversacion_pausada,
    crear_handoff,
    inicializar_db,
    guardar_mensaje,
    obtener_historial,
    purgar_datos_antiguos,
    registrar_evento_si_nuevo,
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
) -> str | None:
    if contexto_producto:
        return contexto_producto
    producto = _producto_desde_texto(texto)
    if producto:
        return producto
    for mensaje in reversed(historial):
        producto = _producto_desde_texto(str(mensaje.get("content", "")))
        if producto:
            return producto
    return None


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
    return f"🛒 Puedes comprar{pronombre} directamente aquí:\n{url}"


async def _resolver_producto_visual_anuncio(msg):
    if msg.es_propio or msg.contexto_producto or not msg.contexto_media_url:
        return msg
    clave = msg.contexto_anuncio_id or hashlib.sha256(
        msg.contexto_media_url.encode("utf-8")
    ).hexdigest()
    if producto := _productos_anuncio_cache.get(clave):
        return replace(msg, contexto_producto=producto)
    try:
        contenido, mime_type = await proveedor.obtener_imagen_anuncio(msg)
        identificador = hashlib.sha256(msg.telefono.encode()).hexdigest()[:32]
        producto = await identificar_producto_desde_imagen(
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
    if not producto:
        logger.info("Miniatura de anuncio sin producto reconocible")
        return msg
    if len(_productos_anuncio_cache) >= 100:
        _productos_anuncio_cache.pop(next(iter(_productos_anuncio_cache)))
    _productos_anuncio_cache[clave] = producto
    logger.info("Producto de anuncio identificado visualmente: %s", producto)
    return replace(msg, contexto_producto=producto)


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
    yield


app = FastAPI(
    title="Escenciales — Agente comercial omnicanal",
    version="3.2.1",
    lifespan=lifespan
)
app.include_router(admin_router)
app.include_router(legal_router)


@app.get("/")
async def health_check():
    return {
        "status": "ok",
        "agent": "Escenciales",
        "version": "3.2.1"
    }


@app.get("/webhook")
async def webhook_verificacion(request: Request):
    resultado = await proveedor.validar_webhook(request)
    if resultado is not None:
        return PlainTextResponse(str(resultado))
    return {"status": "ok"}


async def procesar_mensajes(mensajes):
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
                msg = replace(
                    partes_nuevas[-1],
                    texto=texto_unido,
                    mensaje_id="",
                    contexto_producto=contexto_producto,
                )
                evento_pre_registrado = True

            if msg.es_propio:
                if not msg.telefono:
                    continue
                if not await registrar_evento_si_nuevo(msg.mensaje_id):
                    logger.info("Webhook de operador duplicado ignorado")
                    continue

                conversacion_id = f"{msg.canal}:{msg.telefono}"
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
            producto_conversacion = _producto_de_conversacion(
                msg.contexto_producto, texto, historial
            )
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
            if enviado and not ticket_modelo and not respuesta_tecnica:
                mensaje_compra = _mensaje_compra(producto_conversacion, historial)
                if mensaje_compra:
                    enlace_enviado = await proveedor.enviar_mensaje(
                        msg.telefono, mensaje_compra, canal=msg.canal
                    )
                    if enlace_enviado:
                        await guardar_mensaje(
                            conversacion_id, "assistant", mensaje_compra
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
