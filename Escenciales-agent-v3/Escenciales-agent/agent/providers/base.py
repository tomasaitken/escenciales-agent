from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from fastapi import Request


@dataclass
class MensajeEntrante:
    """Mensaje normalizado — mismo formato sin importar el proveedor."""
    telefono: str
    texto: str
    mensaje_id: str
    es_propio: bool
    canal: str = field(default="whatsapp")
    tipo: str = field(default="text")
    media_id: str | None = field(default=None)
    media_url: str | None = field(default=None)
    mime_type: str | None = field(default=None)


class ProveedorWhatsApp(ABC):
    """Interfaz que cada proveedor de WhatsApp debe implementar."""

    @abstractmethod
    async def parsear_webhook(self, request: Request) -> list[MensajeEntrante]:
        ...

    @abstractmethod
    async def enviar_mensaje(self, destinatario: str, mensaje: str, canal: str) -> bool:
        ...

    async def obtener_audio(self, mensaje: MensajeEntrante) -> tuple[bytes, str]:
        raise NotImplementedError

    async def validar_webhook(self, request: Request) -> dict | int | None:
        return None
