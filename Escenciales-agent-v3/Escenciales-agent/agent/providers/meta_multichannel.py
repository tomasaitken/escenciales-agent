import hashlib
import hmac
import json
import logging
import os
import re
import time
import unicodedata
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import Request, HTTPException
from agent.providers.base import ProveedorWhatsApp, MensajeEntrante

logger = logging.getLogger(__name__)


def _producto_desde_referencia_anuncio(referencia: object) -> str | None:
    """Identifica el producto solo cuando la referencia publicitaria es inequívoca."""
    if not isinstance(referencia, dict):
        return None

    def normalizar(valor: object) -> str:
        texto = unicodedata.normalize("NFKD", str(valor or ""))
        return "".join(
            caracter for caracter in texto
            if not unicodedata.combining(caracter)
        ).lower()

    # Título y URL son más confiables que el cuerpo general del anuncio. Los IDs y
    # source_type no contienen evidencia útil sobre el producto.
    pesos = {
        "headline": 5,
        "source_url": 4,
        "referer_uri": 4,
        "body": 3,
        "ref": 3,
    }
    patrones = {
        "Antena Digital Full HD 4K": (
            r"\bantena\b",
            r"\btv\s*cable\b",
            r"\btelevision\s+digital\b",
            r"\bcanales?\s+(?:nacionales|digitales|hd)\b",
            r"\bfull[\s_-]*hd[\s_-]*4k\b",
        ),
        "Cabezal de ducha": (
            r"\bducha\b",
            r"\bcabezal(?:\s+de)?\s+ducha\b",
            r"\bpresion\s+(?:de\s+)?agua\b",
            r"\bducha\s+masajeadora\b",
        ),
        "Electroestimulador TENS": (
            r"\belectroestimulador\b",
            r"\btens\b",
            r"\belectrodos?\b",
            r"\bterapia\s+muscular\b",
        ),
    }
    puntajes = {producto: 0 for producto in patrones}
    for campo, peso in pesos.items():
        contenido = normalizar(referencia.get(campo, ""))
        for producto, expresiones in patrones.items():
            coincidencias = sum(
                bool(re.search(expresion, contenido))
                for expresion in expresiones
            )
            puntajes[producto] += peso * coincidencias

    ordenados = sorted(puntajes.items(), key=lambda item: item[1], reverse=True)
    (producto, puntaje), (_, segundo) = ordenados[:2]
    if puntaje < 4 or puntaje - segundo < 2:
        return None
    return producto


def _datos_media_referencia_anuncio(
    referencia: object,
) -> tuple[str | None, str | None]:
    """Extrae únicamente la miniatura y el ID no sensible del anuncio."""
    if not isinstance(referencia, dict):
        return None, None
    media_type = str(referencia.get("media_type", "")).lower()
    if media_type == "video":
        media_url = referencia.get("thumbnail_url")
    elif media_type == "image":
        media_url = referencia.get("image_url")
    else:
        media_url = referencia.get("thumbnail_url") or referencia.get("image_url")
    if not isinstance(media_url, str) or not media_url.strip():
        media_url = None
    anuncio_id = referencia.get("source_id") or referencia.get("ad_id")
    if anuncio_id is not None:
        anuncio_id = str(anuncio_id).strip() or None
    return media_url, anuncio_id

class ProveedorMetaMulticanal(ProveedorWhatsApp):

    def __init__(self):
        self.app_id = os.getenv("META_APP_ID")
        self.instagram_app_id = os.getenv("META_INSTAGRAM_APP_ID")
        self.wa_token = os.getenv("META_ACCESS_TOKEN")
        self.page_token = os.getenv("META_PAGE_ACCESS_TOKEN") or self.wa_token
        self.instagram_token = os.getenv("META_INSTAGRAM_ACCESS_TOKEN")
        self.app_secret = os.getenv("META_APP_SECRET")
        self.instagram_app_secret = os.getenv("META_INSTAGRAM_APP_SECRET")
        self.verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN")
        self.wa_phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
        self.ig_page_id = os.getenv("IG_PAGE_ID")
        self.ig_account_id = os.getenv("META_INSTAGRAM_ACCOUNT_ID")
        self.fb_page_id = os.getenv("FB_PAGE_ID")
        self.graph_version = os.getenv("META_GRAPH_API_VERSION", "v25.0")
        self.graph_url = f"https://graph.facebook.com/{self.graph_version}"
        self.instagram_graph_url = f"https://graph.instagram.com/{self.graph_version}"
        self._ecos_bot: dict[str, float] = {}

    async def validar_webhook(self, request: Request):
        params = request.query_params
        if params.get("hub.mode") == "subscribe":
            recibido = params.get("hub.verify_token", "")
            if not self.verify_token:
                raise HTTPException(status_code=503, detail="Webhook no configurado")
            if hmac.compare_digest(recibido, self.verify_token):
                return params.get("hub.challenge", "")
            raise HTTPException(status_code=403, detail="Verify token inválido")
        return None

    async def parsear_webhook(self, request: Request) -> list[MensajeEntrante]:
        raw_body = await request.body()
        if len(raw_body) > 1_000_000:
            raise HTTPException(status_code=413, detail="Payload demasiado grande")
        self._validar_firma(request, raw_body)

        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="JSON inválido") from exc

        mensajes = []

        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                field = change.get("field")
                value = change.get("value", {})

                if field == "smb_message_echoes":
                    for echo in value.get("message_echoes", []):
                        destinatario = echo.get("to", "")
                        if not destinatario:
                            continue
                        tipo = echo.get("type", "unknown")
                        if tipo == "text":
                            texto = echo.get("text", {}).get("body", "")
                        else:
                            texto = f"[Mensaje manual del equipo: {tipo}]"
                        mensajes.append(MensajeEntrante(
                            telefono=destinatario,
                            texto=texto,
                            mensaje_id=echo.get("id", ""),
                            es_propio=True,
                            canal="whatsapp",
                            tipo="operator_echo",
                        ))
                    continue

                if field != "messages":
                    continue
                for msg in value.get("messages", []):
                    referencia = msg.get("referral")
                    contexto_producto = _producto_desde_referencia_anuncio(
                        referencia
                    )
                    contexto_media_url, contexto_anuncio_id = (
                        _datos_media_referencia_anuncio(referencia)
                    )
                    if msg.get("type") == "text":
                        mensajes.append(MensajeEntrante(
                            telefono=msg["from"],
                            texto=msg["text"]["body"],
                            mensaje_id=msg["id"],
                            es_propio=False,
                            canal="whatsapp",
                            contexto_producto=contexto_producto,
                            contexto_media_url=contexto_media_url,
                            contexto_anuncio_id=contexto_anuncio_id,
                        ))
                    elif msg.get("type") == "audio":
                        audio = msg.get("audio", {})
                        mensajes.append(MensajeEntrante(
                            telefono=msg["from"],
                            texto="",
                            mensaje_id=msg["id"],
                            es_propio=False,
                            canal="whatsapp",
                            tipo="audio",
                            media_id=audio.get("id"),
                            mime_type=audio.get("mime_type"),
                            contexto_producto=contexto_producto,
                            contexto_media_url=contexto_media_url,
                            contexto_anuncio_id=contexto_anuncio_id,
                        ))
                    elif msg.get("type") == "image":
                        imagen = msg.get("image", {})
                        mensajes.append(MensajeEntrante(
                            telefono=msg["from"],
                            texto=imagen.get("caption", ""),
                            mensaje_id=msg["id"],
                            es_propio=False,
                            canal="whatsapp",
                            tipo="image",
                            media_id=imagen.get("id"),
                            mime_type=imagen.get("mime_type"),
                            contexto_producto=contexto_producto,
                            contexto_media_url=contexto_media_url,
                            contexto_anuncio_id=contexto_anuncio_id,
                        ))

            for messaging in entry.get("messaging", []):
                sender_id = messaging.get("sender", {}).get("id", "")
                recipient_id = messaging.get("recipient", {}).get("id", "")
                msg = messaging.get("message", {})

                if msg.get("is_echo"):
                    if self._es_echo_del_bot(
                        msg.get("mid", ""), recipient_id, msg.get("text", "")
                    ):
                        continue
                    echo_app_id = str(msg.get("app_id", ""))
                    app_ids_propios = {
                        str(valor) for valor in (self.app_id, self.instagram_app_id)
                        if valor
                    }
                    if echo_app_id in app_ids_propios:
                        continue
                    if sender_id in {self.ig_page_id, self.ig_account_id}:
                        canal = "instagram"
                    elif sender_id == self.fb_page_id:
                        canal = "messenger"
                    else:
                        continue
                    texto = msg.get("text", "")
                    if not texto and msg.get("attachments"):
                        texto = "[Adjunto enviado manualmente por el equipo]"
                    if texto and recipient_id:
                        mensajes.append(MensajeEntrante(
                            telefono=recipient_id,
                            texto=texto,
                            mensaje_id=msg.get("mid", ""),
                            es_propio=True,
                            canal=canal,
                            tipo="operator_echo",
                        ))
                    continue

                if sender_id in [
                    self.ig_page_id,
                    self.ig_account_id,
                    self.fb_page_id,
                    self.wa_phone_id,
                ]:
                    continue

                if recipient_id in {self.ig_page_id, self.ig_account_id}:
                    canal = "instagram"
                else:
                    canal = "messenger"

                texto = msg.get("text", "")
                attachments = msg.get("attachments", [])
                referencia = (
                    messaging.get("referral")
                    or msg.get("referral")
                    or messaging.get("postback", {}).get("referral")
                )
                contexto_producto = _producto_desde_referencia_anuncio(referencia)
                contexto_media_url, contexto_anuncio_id = (
                    _datos_media_referencia_anuncio(referencia)
                )
                imagen = next(
                    (adjunto for adjunto in attachments if adjunto.get("type") == "image"),
                    None,
                )
                if imagen:
                    mensajes.append(MensajeEntrante(
                        telefono=sender_id,
                        texto=texto,
                        mensaje_id=msg.get("mid", ""),
                        es_propio=False,
                        canal=canal,
                        tipo="image",
                        media_url=imagen.get("payload", {}).get("url"),
                        contexto_producto=contexto_producto,
                        contexto_media_url=contexto_media_url,
                        contexto_anuncio_id=contexto_anuncio_id,
                    ))
                elif texto:
                    mensajes.append(MensajeEntrante(
                        telefono=sender_id,
                        texto=texto,
                        mensaje_id=msg.get("mid", ""),
                        es_propio=False,
                        canal=canal,
                        contexto_producto=contexto_producto,
                        contexto_media_url=contexto_media_url,
                        contexto_anuncio_id=contexto_anuncio_id,
                    ))

                for indice, attachment in enumerate(attachments):
                    if attachment.get("type") != "audio":
                        continue
                    payload = attachment.get("payload", {})
                    mensajes.append(MensajeEntrante(
                        telefono=sender_id,
                        texto="",
                        mensaje_id=f"{msg.get('mid', '')}:audio:{indice}",
                        es_propio=False,
                        canal=canal,
                        tipo="audio",
                        media_url=payload.get("url"),
                        contexto_producto=contexto_producto,
                        contexto_media_url=contexto_media_url,
                        contexto_anuncio_id=contexto_anuncio_id,
                    ))

        return mensajes

    async def obtener_audio(self, mensaje: MensajeEntrante) -> tuple[bytes, str]:
        if mensaje.canal == "whatsapp":
            if not mensaje.media_id:
                raise ValueError("Audio de WhatsApp sin media ID")
            async with httpx.AsyncClient(timeout=15) as client:
                metadata = await client.get(
                    f"{self.graph_url}/{mensaje.media_id}",
                    headers={"Authorization": f"Bearer {self.wa_token}"},
                )
                metadata.raise_for_status()
                data = metadata.json()
                media_url = data.get("url")
                mime_type = data.get("mime_type") or mensaje.mime_type
        else:
            media_url = mensaje.media_url
            mime_type = mensaje.mime_type

        if not media_url:
            raise ValueError("Audio sin URL descargable")
        token = self.wa_token if mensaje.canal == "whatsapp" else self.page_token
        contenido, content_type = await self._descargar_media_meta(media_url, token)
        return contenido, (mime_type or content_type or "application/octet-stream")

    async def obtener_imagen_anuncio(
        self, mensaje: MensajeEntrante
    ) -> tuple[bytes, str]:
        if not mensaje.contexto_media_url:
            raise ValueError("Anuncio sin miniatura")
        if mensaje.canal == "whatsapp":
            token = self.wa_token
        elif mensaje.canal == "instagram":
            token = self.instagram_token
        else:
            token = self.page_token
        contenido, content_type = await self._descargar_media_meta(
            mensaje.contexto_media_url,
            token,
            max_bytes=int(os.getenv("MAX_AD_THUMBNAIL_BYTES", "5242880")),
        )
        mime_type = content_type.split(";", 1)[0].strip().lower()
        if mime_type not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
            raise ValueError("Miniatura de anuncio con formato no permitido")
        return contenido, mime_type

    @staticmethod
    def _validar_url_media(url: str) -> None:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        dominios = (
            "facebook.com", "fbcdn.net", "fbsbx.com",
            "cdninstagram.com", "instagram.com",
        )
        if parsed.scheme != "https" or not any(
            host == dominio or host.endswith("." + dominio) for dominio in dominios
        ):
            raise ValueError("URL de audio fuera de dominios Meta permitidos")

    async def _descargar_media_meta(
        self, url: str, token: str | None, max_bytes: int | None = None
    ) -> tuple[bytes, str]:
        max_bytes = max_bytes or int(os.getenv("MAX_AUDIO_BYTES", "10485760"))
        if not token:
            raise ValueError("Token de Meta no configurado para descargar audio")
        headers = {"Authorization": f"Bearer {token}"}
        actual = url

        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            for _ in range(3):
                self._validar_url_media(actual)
                async with client.stream("GET", actual, headers=headers) as resp:
                    if resp.status_code in {301, 302, 303, 307, 308}:
                        location = resp.headers.get("location")
                        if not location:
                            raise ValueError("Redirección de audio sin destino")
                        actual = urljoin(actual, location)
                        continue
                    resp.raise_for_status()
                    declared = int(resp.headers.get("content-length", "0") or 0)
                    if declared > max_bytes:
                        raise ValueError("Audio excede el tamaño permitido")
                    chunks = []
                    total = 0
                    async for chunk in resp.aiter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise ValueError("Audio excede el tamaño permitido")
                        chunks.append(chunk)
                    return b"".join(chunks), resp.headers.get("content-type", "")
        raise ValueError("Demasiadas redirecciones al descargar audio")

    def _validar_firma(self, request: Request, raw_body: bytes) -> None:
        secretos = [
            secreto for secreto in (self.app_secret, self.instagram_app_secret)
            if secreto
        ]
        if not secretos:
            raise HTTPException(status_code=503, detail="Webhook no configurado")

        firma = request.headers.get("x-hub-signature-256", "")
        if not firma.startswith("sha256="):
            raise HTTPException(status_code=401, detail="Firma ausente")

        for secreto in secretos:
            esperada = "sha256=" + hmac.new(
                secreto.encode("utf-8"), raw_body, hashlib.sha256
            ).hexdigest()
            if hmac.compare_digest(firma, esperada):
                return
        raise HTTPException(status_code=401, detail="Firma inválida")

    def _limpiar_ecos_bot(self) -> None:
        ahora = time.monotonic()
        self._ecos_bot = {
            clave: expira for clave, expira in self._ecos_bot.items()
            if expira > ahora
        }

    @staticmethod
    def _clave_echo_texto(destinatario: str, texto: str) -> str:
        return f"texto:{destinatario}:{texto}"

    def _registrar_salida_bot(
        self, destinatario: str, texto: str, mensaje_id: str = ""
    ) -> None:
        self._limpiar_ecos_bot()
        expira = time.monotonic() + 180
        self._ecos_bot[self._clave_echo_texto(destinatario, texto)] = expira
        if mensaje_id:
            self._ecos_bot[f"id:{mensaje_id}"] = expira

    def _descartar_salida_bot(self, destinatario: str, texto: str) -> None:
        self._ecos_bot.pop(self._clave_echo_texto(destinatario, texto), None)

    def _es_echo_del_bot(
        self, mensaje_id: str, destinatario: str, texto: str
    ) -> bool:
        self._limpiar_ecos_bot()
        claves = []
        if mensaje_id:
            claves.append(f"id:{mensaje_id}")
        if destinatario and texto:
            claves.append(self._clave_echo_texto(destinatario, texto))
        return any(clave in self._ecos_bot for clave in claves)

    async def enviar_mensaje(self, destinatario: str, mensaje: str, canal: str) -> bool:
        if canal == "whatsapp":
            if not self.wa_token:
                logger.error("META_ACCESS_TOKEN no configurado")
                return False
            return await self._enviar_whatsapp(destinatario, mensaje)
        if canal == "instagram":
            if not self.instagram_token:
                logger.error("META_INSTAGRAM_ACCESS_TOKEN no configurado")
                return False
            return await self._enviar_graph(destinatario, mensaje, canal)
        if canal == "messenger":
            if not self.page_token:
                logger.error("META_PAGE_ACCESS_TOKEN no configurado")
                return False
            return await self._enviar_graph(destinatario, mensaje, canal)
        logger.error("Canal de salida no soportado: %s", canal)
        return False

    async def _enviar_whatsapp(self, telefono: str, texto: str) -> bool:
        if not self.wa_phone_id:
            logger.error("WHATSAPP_PHONE_NUMBER_ID no configurado")
            return False
        url = f"{self.graph_url}/{self.wa_phone_id}/messages"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {self.wa_token}"},
                json={
                    "messaging_product": "whatsapp",
                    "to": telefono,
                    "type": "text",
                    "text": {"body": texto}
                }
            )
            if resp.status_code != 200:
                logger.error("WA send failed status=%s", resp.status_code)
                return False
            return True

    async def _enviar_graph(self, recipient_id: str, texto: str, canal: str) -> bool:
        if canal == "instagram":
            page_id = self.ig_account_id
            token = self.instagram_token
            graph_url = self.instagram_graph_url
        else:
            page_id = self.fb_page_id
            token = self.page_token
            graph_url = self.graph_url
        if not page_id:
            logger.error("ID de página no configurado para %s", canal)
            return False
        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": texto},
        }
        if canal == "messenger":
            payload["messaging_type"] = "RESPONSE"
        self._registrar_salida_bot(recipient_id, texto)
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                resp = await client.post(
                    f"{graph_url}/{page_id}/messages",
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload,
                )
            except Exception:
                self._descartar_salida_bot(recipient_id, texto)
                raise
            if resp.status_code != 200:
                self._descartar_salida_bot(recipient_id, texto)
                logger.error("Graph send failed status=%s canal=%s", resp.status_code, canal)
                return False
            try:
                mensaje_id = str(resp.json().get("message_id", ""))
            except (ValueError, AttributeError):
                mensaje_id = ""
            if mensaje_id:
                self._registrar_salida_bot(recipient_id, texto, mensaje_id)
            return True
