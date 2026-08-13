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
    "Somos una tienda online ubicada en Santiago de Chile 😊 Hacemos envíos gratis "
    "a todo Chile y el pago es contraentrega: pagas cuando recibes el producto. "
    "También hacemos envíos al extranjero, previa confirmación de las condiciones."
)

PATRONES_DIRECCION_NO_PUBLICABLE = (
    re.compile(r"\bjuan\s+(?:xxiii|23)\b", re.IGNORECASE),
    re.compile(r"\b5560\b"),
)

PATRON_ESCRITURA_NO_LATINA = re.compile(
    "[\u0400-\u052f\u0530-\u058f\u0590-\u08ff\u3040-\u30ff\u3400-\u9fff]"
)

MAX_PALABRAS_RESPUESTA = 55


def acortar_respuesta(respuesta: str, max_palabras: int = MAX_PALABRAS_RESPUESTA) -> str:
    """Limita respuestas comerciales largas sin dejar una frase a medias."""
    palabras = respuesta.split()
    if len(palabras) <= max_palabras:
        return respuesta.strip()

    fragmentos = re.split(r"(?<=[.!?])\s+", respuesta.strip())
    elegidos: list[str] = []
    total = 0
    for fragmento in fragmentos:
        cantidad = len(fragmento.split())
        if total + cantidad > max_palabras:
            break
        elegidos.append(fragmento)
        total += cantidad
    if elegidos:
        return " ".join(elegidos).strip()

    recorte = " ".join(palabras[:max_palabras]).rstrip(",;:")
    return recorte.rstrip(".!?") + "."


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
    """Retira datos operativos que no deben aparecer en respuestas comerciales."""
    negocio = config.get("negocio")
    if isinstance(negocio, dict):
        negocio.pop("direccion_publicada_privacidad", None)
        negocio.pop("telefono", None)
    handoff = config.get("handoff")
    if isinstance(handoff, dict):
        handoff.pop("telefono", None)
    politicas = config.get("politicas")
    if isinstance(politicas, dict) and isinstance(
        politicas.get("derechos_privacidad"), str
    ):
        politicas["derechos_privacidad"] = politicas[
            "derechos_privacidad"
        ].replace("+56 9 3866 3898", "el equipo por este mismo chat")
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
    return acortar_respuesta(respuesta.strip())


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
                "Clasifica el producto PRINCIPAL de esta miniatura publicitaria de "
                "Escenciales. No clasifiques por colores, iconos decorativos, fondo ni "
                "elementos de la interfaz. TENS exige ver el controlador con cables, "
                "parches/electrodos o texto explícito de electroestimulación/TENS. "
                "ANTENA exige hardware de antena/cable/amplificador o texto explícito "
                "de antena, TV o canales. DUCHA exige ver un cabezal/chorro de ducha o "
                "texto explícito de ducha. Si aparecen varios productos, la evidencia "
                "es insuficiente o el producto principal no es claro, usa DESCONOCIDO. "
                "Responde solo ETIQUETA|CONFIANZA, por ejemplo ANTENA|0.97. Las únicas "
                "etiquetas válidas son TENS, ANTENA, DUCHA y DESCONOCIDO."
            ),
            input=[{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Identifica el producto anunciado."},
                    {"type": "input_image", "image_url": data_url, "detail": "high"},
                ],
            }],
            max_output_tokens=30,
            reasoning={"effort": "low"},
            safety_identifier=safety_identifier,
            store=False,
        )
        resultado = re.fullmatch(
            r"\s*(TENS|ANTENA|DUCHA|DESCONOCIDO)\s*\|\s*"
            r"(0(?:\.\d+)?|1(?:\.0+)?)\s*",
            response.output_text,
            flags=re.IGNORECASE,
        )
        if not resultado:
            logger.info("Clasificación visual descartada por formato inválido")
            return None
        etiqueta = resultado.group(1).lower()
        confianza = float(resultado.group(2))
        umbral = min(
            1.0,
            max(0.0, float(os.getenv("AD_PRODUCT_CONFIDENCE_MIN", "0.88"))),
        )
        logger.info(
            "Clasificación visual producto=%s confianza=%.2f umbral=%.2f",
            etiqueta,
            confianza,
            umbral,
        )
        if etiqueta == "desconocido" or confianza < umbral:
            return None
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
