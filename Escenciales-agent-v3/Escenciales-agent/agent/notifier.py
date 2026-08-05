import logging
import os

import httpx

logger = logging.getLogger("escenciales.notifier")


async def notificar_handoff(ticket_id: str, canal: str, motivo: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.info("Handoff creado sin notificación externa ticket=%s", ticket_id)
        return

    admin_url = os.getenv("ADMIN_PUBLIC_URL", "").rstrip("/")
    texto = (
        "🟠 ESENCIALES: conversación pendiente\n"
        f"Canal: {canal}\nMotivo: {motivo}\nCaso: {ticket_id}"
    )
    if admin_url:
        texto += f"\nAbrir cola: {admin_url}/admin"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": texto},
            )
            response.raise_for_status()
    except Exception as exc:
        logger.error("Falló aviso Telegram tipo=%s", type(exc).__name__)
