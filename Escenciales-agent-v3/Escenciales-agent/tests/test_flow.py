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
        self.miniaturas_leidas = 0

    async def enviar_mensaje(self, destinatario, mensaje, canal):
        self.enviados.append((destinatario, mensaje, canal))
        return True

    async def obtener_audio(self, mensaje):
        raise AssertionError("No corresponde audio")

    async def obtener_imagen_anuncio(self, mensaje):
        self.miniaturas_leidas += 1
        return b"miniatura-de-prueba", "image/jpeg"


class FlujoHandoffTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await inicializar_db()
        main._productos_anuncio_cache.clear()

    def test_enlaces_de_compra_son_oficiales_y_no_se_repiten(self):
        casos = {
            "Antena Digital Full HD 4K": "53910086058352",
            "Cabezal de ducha": "53942908322160",
            "Electroestimulador TENS": "54012229452144",
        }
        for producto, variante in casos.items():
            mensaje = main._mensaje_compra(producto, [])
            self.assertIn("🛒", mensaje)
            self.assertIn(variante, mensaje)
            self.assertIn("PAGA Contra ENTREGA", mensaje)
            self.assertIn("este mismo chat", mensaje)
            self.assertNotIn("3866 3898", mensaje)
            self.assertIsNone(
                main._mensaje_compra(
                    producto,
                    [{"role": "assistant", "content": mensaje}],
                )
            )

    def test_enlace_solo_con_intencion_explicita_de_compra(self):
        for texto in (
            "Hola, quiero más información",
            "¿Cuánto cuesta la ducha?",
            "¿Cómo funciona la antena?",
        ):
            with self.subTest(texto=texto):
                self.assertFalse(main._debe_enviar_enlace(texto, []))

        for texto in (
            "¿Cómo la compro?",
            "Quiero comprar el TENS",
            "Mándame el link para comprar",
            "¿Cómo hago el pedido?",
        ):
            with self.subTest(texto=texto):
                self.assertTrue(main._debe_enviar_enlace(texto, []))

        historial = [{
            "role": "assistant",
            "content": "¿Quieres que te ayude a comprarla?",
        }]
        self.assertTrue(main._debe_enviar_enlace("Sí", historial))

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
            contexto_producto="Antena Digital Full HD 4K",
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

        self.assertEqual(len(proveedor.enviados), 2)
        self.assertEqual(generar.await_count, 1)
        self.assertEqual(
            generar.await_args.args[0],
            "[Producto identificado desde el anuncio de Meta: "
            "Antena Digital Full HD 4K]\n"
            "ola\nkiero la antena\ncuanto sale y como la compro",
        )
        self.assertIn("🛒", proveedor.enviados[1][1])
        self.assertIn("53910086058352", proveedor.enviados[1][1])

    async def test_consulta_generica_de_anuncio_llega_al_modelo_con_producto(self):
        contacto = "569" + uuid.uuid4().hex[:8]
        proveedor = ProveedorFalso()
        mensaje = MensajeEntrante(
            telefono=contacto,
            texto="Hello! Can I get more info on this?\nHola",
            mensaje_id="msg-" + uuid.uuid4().hex,
            es_propio=False,
            canal="whatsapp",
            contexto_producto="Antena Digital Full HD 4K",
        )
        generar = AsyncMock(return_value="Claro, te cuento sobre la antena HD.")

        with patch.object(main, "proveedor", proveedor), patch.object(
            main, "generar_respuesta", generar
        ):
            await main.procesar_mensajes([mensaje])

        self.assertEqual(len(proveedor.enviados), 1)
        self.assertEqual(generar.await_count, 1)
        self.assertEqual(
            generar.await_args.args[0],
            "[Producto identificado desde el anuncio de Meta: "
            "Antena Digital Full HD 4K]\n"
            "Hello! Can I get more info on this?\nHola",
        )

    async def test_anuncio_de_video_generico_se_identifica_por_miniatura(self):
        contacto = "569" + uuid.uuid4().hex[:8]
        proveedor = ProveedorFalso()
        mensaje = MensajeEntrante(
            telefono=contacto,
            texto="Hola, quiero más información",
            mensaje_id="msg-" + uuid.uuid4().hex,
            es_propio=False,
            canal="whatsapp",
            contexto_media_url="https://scontent.xx.fbcdn.net/tens.jpg",
            contexto_anuncio_id="anuncio-video-tens",
        )
        generar = AsyncMock(return_value="Claro, te cuento sobre el TENS.")
        clasificar = AsyncMock(return_value="Electroestimulador TENS")

        with patch.object(main, "proveedor", proveedor), patch.object(
            main, "generar_respuesta", generar
        ), patch.object(
            main, "identificar_producto_desde_imagen", clasificar
        ):
            await main.procesar_mensajes([mensaje])

        self.assertEqual(proveedor.miniaturas_leidas, 1)
        self.assertEqual(clasificar.await_count, 1)
        self.assertEqual(len(proveedor.enviados), 1)
        self.assertEqual(
            generar.await_args.args[0],
            "[Producto identificado desde el anuncio de Meta: "
            "Electroestimulador TENS]\n"
            "Hola, quiero más información",
        )

    async def test_anuncio_nuevo_dudoso_no_hereda_producto_anterior(self):
        contacto = "569" + uuid.uuid4().hex[:8]
        proveedor = ProveedorFalso()
        mensaje = MensajeEntrante(
            telefono=contacto,
            texto="Hola, quiero más información",
            mensaje_id="msg-" + uuid.uuid4().hex,
            es_propio=False,
            canal="whatsapp",
            contexto_media_url="https://scontent.xx.fbcdn.net/anuncio-dudoso.jpg",
            contexto_anuncio_id="anuncio-nuevo-dudoso",
        )
        historial_anterior = [{
            "role": "assistant",
            "content": "La ducha cuesta $23.990.",
        }]
        generar = AsyncMock(return_value="No debería adivinar el producto")

        with patch.object(main, "proveedor", proveedor), patch.object(
            main, "identificar_producto_desde_imagen", AsyncMock(return_value=None)
        ), patch.object(
            main, "obtener_historial", AsyncMock(return_value=historial_anterior)
        ), patch.object(main, "generar_respuesta", generar):
            await main.procesar_mensajes([mensaje])

        generar.assert_not_awaited()
        self.assertEqual(len(proveedor.enviados), 1)
        respuesta = proveedor.enviados[0][1]
        self.assertIn("asegurarme", respuesta)
        self.assertIn("antena HD", respuesta)
        self.assertIn("electroestimulador TENS", respuesta)
        self.assertIn("ducha", respuesta)
        self.assertNotIn("$23.990", respuesta)

    async def test_conflicto_miniatura_metadatos_no_elije_ninguno(self):
        mensaje = MensajeEntrante(
            telefono="569" + uuid.uuid4().hex[:8],
            texto="Más información",
            mensaje_id="msg-" + uuid.uuid4().hex,
            es_propio=False,
            canal="whatsapp",
            contexto_producto="Cabezal de ducha",
            contexto_media_url="https://scontent.xx.fbcdn.net/tens.jpg",
            contexto_anuncio_id="anuncio-conflictivo",
        )
        proveedor = ProveedorFalso()
        with patch.object(main, "proveedor", proveedor), patch.object(
            main,
            "identificar_producto_desde_imagen",
            AsyncMock(return_value="Electroestimulador TENS"),
        ):
            resuelto = await main._resolver_producto_visual_anuncio(mensaje)

        self.assertIsNone(resuelto.contexto_producto)

    def test_producto_anterior_solo_se_reutiliza_sin_anuncio_nuevo(self):
        historial = [{"role": "assistant", "content": "Te cuento sobre la ducha."}]
        self.assertEqual(
            main._producto_de_conversacion(None, "¿Y el precio?", historial),
            "Cabezal de ducha",
        )
        self.assertIsNone(
            main._producto_de_conversacion(
                None,
                "Quiero más información",
                historial,
                nuevo_contexto_anuncio=True,
            )
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

    async def test_ubicacion_tiene_el_mismo_estandar_en_los_tres_canales(self):
        self.assertIsNotNone(
            main._respuesta_ubicacion_comercial("¿De dónde son?", None)
        )
        self.assertIsNotNone(
            main._respuesta_ubicacion_comercial("¿Tienen local?", None)
        )
        generar = AsyncMock(return_value="No debería usarse")
        for canal in ("whatsapp", "messenger", "instagram"):
            with self.subTest(canal=canal):
                contacto = f"{canal}-{uuid.uuid4().hex[:10]}"
                proveedor = ProveedorFalso()
                mensaje = MensajeEntrante(
                    telefono=contacto,
                    texto="¿Dónde están ubicados?",
                    mensaje_id="msg-" + uuid.uuid4().hex,
                    es_propio=False,
                    canal=canal,
                )
                with patch.object(main, "proveedor", proveedor), patch.object(
                    main, "generar_respuesta", generar
                ):
                    await main.procesar_mensajes([mensaje])

                self.assertEqual(len(proveedor.enviados), 1)
                respuesta = proveedor.enviados[0][1]
                self.assertIn("Santiago de Chile", respuesta)
                self.assertIn("envíos gratis a todo Chile", respuesta)
                self.assertIn("pago es contraentrega", respuesta)
                self.assertIn("¿Con cuál producto", respuesta)

        self.assertEqual(generar.await_count, 0)

    async def test_ubicacion_con_producto_no_vuelve_a_preguntar_cual(self):
        contacto = "ig-" + uuid.uuid4().hex[:10]
        proveedor = ProveedorFalso()
        mensaje = MensajeEntrante(
            telefono=contacto,
            texto="¿Dónde están ubicados?",
            mensaje_id="msg-" + uuid.uuid4().hex,
            es_propio=False,
            canal="instagram",
            contexto_producto="Electroestimulador TENS",
        )

        with patch.object(main, "proveedor", proveedor), patch.object(
            main, "generar_respuesta", AsyncMock(return_value="No debería usarse")
        ):
            await main.procesar_mensajes([mensaje])

        respuesta = proveedor.enviados[0][1]
        self.assertIn("electroestimulador TENS", respuesta)
        self.assertNotIn("cuál producto", respuesta)

    async def test_enlace_programa_seguimiento_y_nuevo_mensaje_lo_cancela(self):
        contacto = "fb-" + uuid.uuid4().hex[:10]
        proveedor = ProveedorFalso()
        compra = MensajeEntrante(
            telefono=contacto,
            texto="Quiero comprar la antena",
            mensaje_id="msg-" + uuid.uuid4().hex,
            es_propio=False,
            canal="messenger",
            contexto_producto="Antena Digital Full HD 4K",
        )
        programar = AsyncMock()
        cancelar = AsyncMock(return_value=0)

        with patch.object(main, "proveedor", proveedor), patch.object(
            main, "generar_respuesta", AsyncMock(return_value="Claro, te ayudo.")
        ), patch.object(
            main, "programar_seguimiento_compra", programar
        ), patch.object(
            main, "cancelar_seguimientos_compra", cancelar
        ), patch.dict(os.environ, {
            "PURCHASE_FOLLOWUP_ENABLED": "true",
            "PURCHASE_FOLLOWUP_MINUTES": "15",
        }):
            await main.procesar_mensajes([compra])

        self.assertEqual(len(proveedor.enviados), 2)
        self.assertIn("53910086058352", proveedor.enviados[1][1])
        programar.assert_awaited_once_with(
            f"messenger:{contacto}",
            "messenger",
            contacto,
            "Antena Digital Full HD 4K",
            minutos=15.0,
        )
        cancelar.assert_awaited_once_with(f"messenger:{contacto}")


if __name__ == "__main__":
    unittest.main()
