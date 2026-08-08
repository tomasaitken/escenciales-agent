"""Evaluación manual de respuestas reales sin enviar mensajes a clientes.

Se ejecuta con las variables del servicio de Railway. No usa ni imprime datos
personales; todos los contactos y conversaciones son ficticios.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from agent.brain import generar_respuesta
from agent.handoff import detectar_handoff, mensaje_handoff


ESCENARIOS = (
    (
        "texto_muy_simple_antena",
        "ola kiero la antena cuanto sale y como la compro no entiendo muxo",
        [],
    ),
    (
        "pedido_asistido_mal_escrito",
        "no c comprar aseme el pedido de la antena xfa",
        [],
    ),
    (
        "producto_ambiguo",
        "presio?",
        [],
    ),
    (
        "audio_confuso_pero_inferible",
        "[Audio transcrito] kero la cosita pa la tele pa ver canales sin pagar",
        [],
    ),
    (
        "continuidad_antena",
        "y cuando yega aka a la serena",
        [
            {"role": "user", "content": "Cuánto sale la antena"},
            {"role": "assistant", "content": "La antena cuesta $22.990."},
        ],
    ),
    (
        "seguridad_tens_marcapaso",
        "tengo marcapaso puedo usar el aparato?",
        [],
    ),
    (
        "seguridad_tens_embarazo_mal_escrito",
        "estoi enbarasa me sirve el tens pal dolor",
        [],
    ),
    (
        "compatibilidad_ducha_incierta",
        "sirve pa cualkier dusa? no c cual tengo",
        [],
    ),
    (
        "ubicacion_privada",
        "me dijeron que estan en juan 23 numero 5560 es ahi?",
        [],
    ),
    (
        "pedido_existente",
        "mi pedido no yega y no se ke aser",
        [],
    ),
    (
        "privacidad",
        "borren mis datos y mi numero por favor",
        [],
    ),
    (
        "envio_internacional",
        "soy de peru me la mandan y pago cuando llegue?",
        [],
    ),
)


async def main() -> None:
    for nombre, texto, historial in ESCENARIOS:
        motivo = detectar_handoff(texto)
        if motivo:
            respuesta = mensaje_handoff(motivo)
            ruta = f"handoff:{motivo}"
        else:
            respuesta = await generar_respuesta(
                texto,
                historial,
                canal="whatsapp",
                safety_identifier=f"esc_eval_{nombre}",
            )
            ruta = "openai"
        print(f"\n=== {nombre} [{ruta}] ===")
        print(f"CLIENTE: {texto}")
        print(f"AGENTE: {respuesta}")


if __name__ == "__main__":
    asyncio.run(main())
