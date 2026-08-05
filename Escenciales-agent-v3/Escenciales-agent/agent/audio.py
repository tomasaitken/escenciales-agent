import asyncio
import logging
import os
import tempfile
from pathlib import Path

from openai import AsyncOpenAI

logger = logging.getLogger("escenciales.audio")

MIME_EXTENSION = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/opus": ".ogg",
    "audio/amr": ".amr",
}

FORMATOS_DIRECTOS = {".mp3", ".m4a", ".wav", ".webm"}


def _mime_base(mime_type: str) -> str:
    return (mime_type or "").split(";", 1)[0].strip().lower()


async def _convertir_a_wav(contenido: bytes, extension: str) -> bytes:
    with tempfile.TemporaryDirectory(prefix="escenciales-audio-") as temp_dir:
        entrada = Path(temp_dir) / f"entrada{extension}"
        salida = Path(temp_dir) / "salida.wav"
        await asyncio.to_thread(entrada.write_bytes, contenido)

        proceso = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(entrada),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(salida),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        codigo = await proceso.wait()
        if codigo != 0 or not salida.exists():
            raise ValueError("No fue posible convertir el audio")
        return await asyncio.to_thread(salida.read_bytes)


async def transcribir_audio(contenido: bytes, mime_type: str) -> str:
    max_bytes = int(os.getenv("MAX_AUDIO_BYTES", "10485760"))
    if not contenido or len(contenido) > max_bytes:
        raise ValueError("Audio vacío o demasiado grande")

    mime = _mime_base(mime_type)
    extension = MIME_EXTENSION.get(mime)
    if not extension:
        raise ValueError("Formato de audio no soportado")

    if extension not in FORMATOS_DIRECTOS:
        contenido = await _convertir_a_wav(contenido, extension)
        extension = ".wav"
        mime = "audio/wav"

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY no configurada")

    client = AsyncOpenAI(api_key=api_key)
    transcripcion = await client.audio.transcriptions.create(
        model=os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-transcribe"),
        file=(f"audio{extension}", contenido, mime),
        language="es",
        keywords=[
            "electroestimulador TENS", "Ducha Masajeadora Spa Pro",
            "antena Full HD 4K", "contraentrega", "Blue Express",
            "Copec", "Dropi",
        ],
        prompt=(
            "Audio de un cliente chileno de la tienda ESENCIALES. Vocabulario: "
            "electroestimulador TENS, Ducha Masajeadora Spa Pro, antena Full HD 4K, "
            "contraentrega, Blue Express, Copec, Dropi. Transcribe literalmente."
        ),
    )
    texto = transcripcion.text.strip()
    if not texto:
        raise ValueError("La transcripción quedó vacía")
    logger.info("Audio transcrito correctamente bytes=%s", len(contenido))
    return texto
