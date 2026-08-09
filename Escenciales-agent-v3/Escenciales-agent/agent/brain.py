import base64
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

PATRON_ESCRITURA_NO_LATINA = re.compile(
    "[\u0400-\u052f\u0530-\u058f\u0590-\u08ff\u3040-\u30ff\u3400-\u9fff]"
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
    if PATRON_ESCRITURA_NO_LATINA.search(respuesta):
        logger.warning("Se eliminó escritura no latina de la respuesta del agente")
        respuesta = PATRON_ESCRITURA_NO_LATINA.sub("", respuesta)
        respuesta = re.sub(r"[ \t]{2,}", " ", respuesta)
    return respuesta.strip()


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


async def identificar_producto_desde_imagen(
    contenido: bytes,
    mime_type: str,
    safety_identifier: str | None = None,
) -> str | None:
    """Clasifica una miniatura de anuncio dentro del catálogo cerrado."""
    if not contenido or len(contenido) > 5_242_880:
        return None
    formatos = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    if mime_type not in formatos:
        return None
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    data_url = (
        f"data:{mime_type};base64,"
        + base64.b64encode(contenido).decode("ascii")
    )
    try:
        client = AsyncOpenAI(api_key=api_key)
        response = await client.responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-5.6-terra"),
            instructions=(
                "Clasifica esta miniatura de un anuncio de la tienda Escenciales. "
                "Responde exactamente con una de estas cuatro etiquetas, sin explicar: "
                "TENS, ANTENA, DUCHA o DESCONOCIDO. Usa TENS si aparece un "
                "electroestimulador con electrodos; ANTENA si aparece una antena de TV; "
                "DUCHA si aparece un cabezal de ducha. Si no es claro, DESCONOCIDO."
            ),
            input=[{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Identifica el producto anunciado."},
                    {"type": "input_image", "image_url": data_url, "detail": "low"},
                ],
            }],
            max_output_tokens=80,
            reasoning={"effort": "low"},
            safety_identifier=safety_identifier,
            store=False,
        )
        etiqueta = re.sub(r"[^a-z]", "", response.output_text.lower())
        return {
            "tens": "Electroestimulador TENS",
            "antena": "Antena Digital Full HD 4K",
            "ducha": "Cabezal de ducha",
        }.get(etiqueta)
    except Exception as exc:
        logger.warning(
            "No se pudo clasificar miniatura de anuncio tipo=%s",
            type(exc).__name__,
        )
        return None
