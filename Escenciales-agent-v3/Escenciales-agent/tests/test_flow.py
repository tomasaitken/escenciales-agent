import os
import unittest
import uuid
from unittest.mock import AsyncMock, patch

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["ENVIRONMENT"] = "development"

from agent import main  # noqa: E402
from agent.memory import (  # noqa: E402
    conversacion_pausada,
    inicializar_db,
    listar_handoffs,
    resolver_handoff,
)
from agent.providers.base import MensajeEntrante  # noqa: E402


class ProveedorFalso:
    def __init__(self):
        self.enviados = []

    async def enviar_mensaje(self, destinatario, mensaje, canal):
        self.enviados.append((destinatario, mensaje, canal))
        return True

    async def obtener_audio(self, mensaje):
        raise AssertionError("No corresponde audio")


class FlujoHandoffTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await inicializar_db()

    async def test_pedido_asistido_responde_una_vez_y_pausa(self):
        contacto = "569" + uuid.uuid4().hex[:8]
        proveedor = ProveedorFalso()
        mensaje = MensajeEntrante(
            telefono=contacto,
            texto="No sé comprar, ¿me pueden hacer el pedido?",
            mensaje_id="msg-" + uuid.uuid4().hex,
            es_propio=False,
            canal="whatsapp",
        )

        with patch.object(main, "proveedor", proveedor), patch.object(
            main, "notificar_handoff", AsyncMock()
        ):
            await main.procesar_mensajes([mensaje])
            self.assertEqual(len(proveedor.enviados), 1)
            self.assertIn("persona del equipo", proveedor.enviados[0][1])

            conversacion = f"whatsapp:{contacto}"
            self.assertTrue(await conversacion_pausada(conversacion))

            segundo = MensajeEntrante(
                telefono=contacto,
                texto="Mi dirección es...",
                mensaje_id="msg-" + uuid.uuid4().hex,
                es_propio=False,
                canal="whatsapp",
            )
            await main.procesar_mensajes([segundo])
            self.assertEqual(len(proveedor.enviados), 1)

            pendientes = await listar_handoffs("pendiente")
            ticket = next(t for t in pendientes if t["conversacion_id"] == conversacion)
            self.assertTrue(await resolver_handoff(ticket["id"]))
            self.assertFalse(await conversacion_pausada(conversacion))

    async def test_respuesta_manual_pausa_el_bot_sin_responder(self):
        contacto = "569" + uuid.uuid4().hex[:8]
        proveedor = ProveedorFalso()
        respuesta_manual = MensajeEntrante(
            telefono=contacto,
            texto="Hola, yo te ayudo personalmente con el pedido.",
            mensaje_id="echo-" + uuid.uuid4().hex,
            es_propio=True,
            canal="whatsapp",
            tipo="operator_echo",
        )

        with patch.object(main, "proveedor", proveedor):
            await main.procesar_mensajes([respuesta_manual])
            self.assertEqual(proveedor.enviados, [])

            conversacion = f"whatsapp:{contacto}"
            self.assertTrue(await conversacion_pausada(conversacion))

            cliente = MensajeEntrante(
                telefono=contacto,
                texto="Gracias, esta es mi dirección.",
                mensaje_id="msg-" + uuid.uuid4().hex,
                es_propio=False,
                canal="whatsapp",
            )
            await main.procesar_mensajes([cliente])
            self.assertEqual(proveedor.enviados, [])

            pendientes = await listar_handoffs("pendiente")
            ticket = next(t for t in pendientes if t["conversacion_id"] == conversacion)
            self.assertEqual(ticket["motivo"], "operador_manual")


if __name__ == "__main__":
    unittest.main()
