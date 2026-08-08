import asyncio
import os
import unittest
import uuid
from unittest.mock import AsyncMock, patch

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["ENVIRONMENT"] = "development"
os.environ["MESSAGE_DEBOUNCE_SECONDS"] = "0"

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

    async def test_imagen_se_deriva_y_pausa_sin_intentar_interpretarla(self):
        contacto = "ig-" + uuid.uuid4().hex[:8]
        proveedor = ProveedorFalso()
        imagen = MensajeEntrante(
            telefono=contacto,
            texto="Esta conexión sirve?",
            mensaje_id="img-" + uuid.uuid4().hex,
            es_propio=False,
            canal="instagram",
            tipo="image",
            media_url="https://lookaside.fbsbx.com/imagen.jpg",
        )

        with patch.object(main, "proveedor", proveedor), patch.object(
            main, "notificar_handoff", AsyncMock()
        ):
            await main.procesar_mensajes([imagen])

        self.assertEqual(len(proveedor.enviados), 1)
        self.assertIn("recibí la foto", proveedor.enviados[0][1])
        self.assertTrue(await conversacion_pausada(f"instagram:{contacto}"))

    async def test_promesa_del_modelo_crea_handoff_real(self):
        contacto = "569" + uuid.uuid4().hex[:8]
        proveedor = ProveedorFalso()
        mensaje = MensajeEntrante(
            telefono=contacto,
            texto="No estoy seguro de la conexión",
            mensaje_id="msg-" + uuid.uuid4().hex,
            es_propio=False,
            canal="whatsapp",
        )

        with patch.object(main, "proveedor", proveedor), patch.object(
            main, "generar_respuesta", AsyncMock(
                return_value="Una persona del equipo revisará esto contigo."
            )
        ), patch.object(main, "notificar_handoff", AsyncMock()):
            await main.procesar_mensajes([mensaje])

        self.assertEqual(len(proveedor.enviados), 1)
        self.assertTrue(await conversacion_pausada(f"whatsapp:{contacto}"))

    async def test_fragmentos_consecutivos_generan_una_sola_respuesta(self):
        contacto = "569" + uuid.uuid4().hex[:8]
        proveedor = ProveedorFalso()
        primero = MensajeEntrante(
            telefono=contacto,
            texto="ola",
            mensaje_id="msg-" + uuid.uuid4().hex,
            es_propio=False,
            canal="whatsapp",
        )
        segundo = MensajeEntrante(
            telefono=contacto,
            texto="kiero la antena",
            mensaje_id="msg-" + uuid.uuid4().hex,
            es_propio=False,
            canal="whatsapp",
        )
        tercero = MensajeEntrante(
            telefono=contacto,
            texto="cuanto sale y como la compro",
            mensaje_id="msg-" + uuid.uuid4().hex,
            es_propio=False,
            canal="whatsapp",
        )
        generar = AsyncMock(return_value="La antena cuesta $22.990.")

        with patch.dict(os.environ, {"MESSAGE_DEBOUNCE_SECONDS": "0.2"}), patch.object(
            main, "proveedor", proveedor
        ), patch.object(main, "generar_respuesta", generar):
            tarea_1 = asyncio.create_task(main.procesar_mensajes([primero]))
            await asyncio.sleep(0.01)
            tarea_2 = asyncio.create_task(main.procesar_mensajes([segundo]))
            await asyncio.sleep(0.05)
            tarea_3 = asyncio.create_task(main.procesar_mensajes([tercero]))
            await asyncio.gather(tarea_1, tarea_2, tarea_3)

        self.assertEqual(len(proveedor.enviados), 1)
        self.assertEqual(generar.await_count, 1)
        self.assertEqual(
            generar.await_args.args[0],
            "ola\nkiero la antena\ncuanto sale y como la compro",
        )

    async def test_fragmentos_en_un_mismo_webhook_tambien_se_agrupan(self):
        contacto = "569" + uuid.uuid4().hex[:8]
        proveedor = ProveedorFalso()
        mensajes = [
            MensajeEntrante(
                telefono=contacto,
                texto=texto,
                mensaje_id="msg-" + uuid.uuid4().hex,
                es_propio=False,
                canal="messenger",
            )
            for texto in ("hola", "kiero", "la antena")
        ]
        generar = AsyncMock(return_value="La antena cuesta $22.990.")

        with patch.dict(os.environ, {"MESSAGE_DEBOUNCE_SECONDS": "0.05"}), patch.object(
            main, "proveedor", proveedor
        ), patch.object(main, "generar_respuesta", generar):
            await main.procesar_mensajes(mensajes)

        self.assertEqual(len(proveedor.enviados), 1)
        self.assertEqual(generar.await_count, 1)
        self.assertEqual(generar.await_args.args[0], "hola\nkiero\nla antena")


if __name__ == "__main__":
    unittest.main()
