import hashlib
import hmac
import json
import logging
import os
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import Request, HTTPException
from agent.providers.base import ProveedorWhatsApp, MensajeEntrante

logger = logging.getLogger(__name__)

class ProveedorMetaMulticanal(ProveedorWhatsApp):

    def __init__(self):
        self.wa_token = os.getenv("META_ACCESS_TOKEN")
        self.page_token = os.getenv("META_PAGE_ACCESS_TOKEN") or self.wa_token
        self.app_secret = os.getenv("META_APP_SECRET")
        self.verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN")
        self.wa_phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
        self.ig_page_id = os.getenv("IG_PAGE_ID")
        self.fb_page_id = os.getenv("FB_PAGE_ID")
        self.graph_version = os.getenv("META_GRAPH_API_VERSION", "v25.0")
        self.graph_url = f"https://graph.facebook.com/{self.graph_version}"

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
                    if msg.get("type") == "text":
                        mensajes.append(MensajeEntrante(
                            telefono=msg["from"],
                            texto=msg["text"]["body"],
                            mensaje_id=msg["id"],
                            es_propio=False,
                            canal="whatsapp",
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
                        ))

            for messaging in entry.get("messaging", []):
                sender_id = messaging.get("sender", {}).get("id", "")
                recipient_id = messaging.get("recipient", {}).get("id", "")
                msg = messaging.get("message", {})

                if sender_id in [self.ig_page_id, self.fb_page_id, self.wa_phone_id]:
                    continue

                if recipient_id == self.ig_page_id:
                    canal = "instagram"
                else:
                    canal = "messenger"

                texto = msg.get("text", "")
                if texto:
                    mensajes.append(MensajeEntrante(
                        telefono=sender_id,
                        texto=texto,
                        mensaje_id=msg.get("mid", ""),
                        es_propio=False,
                        canal=canal,
                    ))

                for indice, attachment in enumerate(msg.get("attachments", [])):
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
        self, url: str, token: str | None
    ) -> tuple[bytes, str]:
        max_bytes = int(os.getenv("MAX_AUDIO_BYTES", "10485760"))
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
        if not self.app_secret:
            raise HTTPException(status_code=503, detail="Webhook no configurado")

        firma = request.headers.get("x-hub-signature-256", "")
        if not firma.startswith("sha256="):
            raise HTTPException(status_code=401, detail="Firma ausente")

        esperada = "sha256=" + hmac.new(
            self.app_secret.encode("utf-8"), raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(firma, esperada):
            raise HTTPException(status_code=401, detail="Firma inválida")

    async def enviar_mensaje(self, destinatario: str, mensaje: str, canal: str) -> bool:
        if canal == "whatsapp":
            if not self.wa_token:
                logger.error("META_ACCESS_TOKEN no configurado")
                return False
            return await self._enviar_whatsapp(destinatario, mensaje)
        if canal in {"instagram", "messenger"}:
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
        page_id = self.ig_page_id if canal == "instagram" else self.fb_page_id
        if not page_id:
            logger.error("ID de página no configurado para %s", canal)
            return False
        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": texto},
        }
        if canal == "messenger":
            payload["messaging_type"] = "RESPONSE"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.graph_url}/{page_id}/messages",
                headers={"Authorization": f"Bearer {self.page_token}"},
                json=payload,
            )
            if resp.status_code != 200:
                logger.error("Graph send failed status=%s canal=%s", resp.status_code, canal)
                return False
            return True
