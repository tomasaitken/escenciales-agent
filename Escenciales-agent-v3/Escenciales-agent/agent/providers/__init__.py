import os
from agent.providers.base import ProveedorWhatsApp


def obtener_proveedor() -> ProveedorWhatsApp:
    """Retorna el proveedor configurado en .env."""
    proveedor = os.getenv("WHATSAPP_PROVIDER", "meta_multichannel").lower()
    if proveedor == "meta_multichannel":
        from agent.providers.meta_multichannel import ProveedorMetaMulticanal
        return ProveedorMetaMulticanal()
    else:
        raise ValueError(f"Proveedor no soportado: {proveedor}. Usa: meta_multichannel")
