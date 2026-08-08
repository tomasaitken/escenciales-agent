import os
import re
import yaml
import logging
from pathlib import Path
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("escenciales")

BASE_DIR = Path(__file__).resolve().parent.parent

CANAL_LABELS = {
    "whatsapp":  "WhatsApp",
    "instagram": "Instagram DM",
    "messenger": "Facebook Messenger",
}

RESPUESTA_UBICACION_SEGURA = (
    "Estamos ubicados en Santiago de Chile. Hacemos envíos a todo Chile y también "
    "al extranjero. Si me dices tu ciudad o país, te ayudo con el despacho."
)

PATRONES_DIRECCION_NO_PUBLICABLE = (
    re.compile(r"\bjuan\s+(?:xxiii|23)\b", re.IGNORECASE),
    re.compile(r"\b5560\b"),
)


def cargar_prompts_config() -> dict:
    try:
        with (BASE_DIR / "config" / "prompts.yaml").open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.error("config/prompts.yaml no encontrado")
        return {}


def cargar_business_config() -> dict:
    try:
        with (BASE_DIR / "config" / "business.yaml").open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.error("config/business.yaml no encontrado")
        return {}


def _config_para_agente(config: dict) -> dict:
    """Retira datos legales que no deben aparecer en respuestas comerciales."""
    negocio = config.get("negocio")
    if isinstance(negocio, dict):
        negocio.pop("direccion_publicada_privacidad", None)
    return config


def sanitizar_respuesta(respuesta: str) -> str:
    """Impide que una dirección administrativa se filtre al cliente."""
    if any(patron.search(respuesta) for patron in PATRONES_DIRECCION_NO_PUBLICABLE):
        logger.warning("Se bloqueó una dirección exacta en la respuesta del agente")
        return RESPUESTA_UBICACION_SEGURA
    return respuesta


def cargar_system_prompt(canal: str = "whatsapp") -> str:
    config = cargar_prompts_config()
    base = config.get("system_prompt", "Eres el asistente comercial de Escenciales. Responde en español.")
    negocio = yaml.safe_dump(
        _config_para_agente(cargar_business_config()),
        allow_unicode=True,
        sort_keys=False,
    )
    canal_label = CANAL_LABELS.get(canal, canal)
    return (
        base
        + f"\n\nCanal activo: {canal_label}."
        + "\n\n<fuente_de_verdad_negocio>\n"
        + negocio
        + "</fuente_de_verdad_negocio>"
    )


def obtener_mensaje_error() -> str:
    config = cargar_prompts_config()
    return config.get("error_message", "Uy, se me cruzaron los cables un segundo. ¿Me lo puedes repetir?")


def obtener_mensaje_fallback() -> str:
    config = cargar_prompts_config()
    return config.get("fallback_message", "No logré procesar tu mensaje. ¿Puedes reformularlo?")


async def generar_respuesta(
    mensaje: str,
    historial: list[dict],
    canal: str = "whatsapp",
    safety_identifier: str | None = None,
) -> str:
    if not mensaje or len(mensaje.strip()) < 2:
        return obtener_mensaje_fallback()
    if len(mensaje) > 4000:
        return "Tu mensaje es muy largo para procesarlo de una vez. ¿Puedes resumirlo?"

    system_prompt = cargar_system_prompt(canal)

    mensajes = [
        {"role": msg["role"], "content": msg["content"]}
        for msg in historial
    ]
    mensajes.append({"role": "user", "content": mensaje})

    try:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.error("OPENAI_API_KEY no configurada")
            return obtener_mensaje_error()
        client = AsyncOpenAI(api_key=api_key)
        response = await client.responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-5.6-terra"),
            instructions=system_prompt,
            input=mensajes[-20:],
            max_output_tokens=int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "700")),
            reasoning={
                "effort": os.getenv("OPENAI_REASONING_EFFORT", "low"),
            },
            safety_identifier=safety_identifier,
            store=False,
        )
        respuesta = sanitizar_respuesta(response.output_text.strip())
        if not respuesta:
            return obtener_mensaje_error()
        logger.info(
            "[%s] OpenAI respondió (%s in / %s out tokens)",
            canal.upper(),
            response.usage.input_tokens if response.usage else "?",
            response.usage.output_tokens if response.usage else "?",
        )
        return respuesta

    except Exception as exc:
        logger.error("Error OpenAI API tipo=%s", type(exc).__name__)
        return obtener_mensaje_error()
