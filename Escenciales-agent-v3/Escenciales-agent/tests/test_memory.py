import os
import unittest
import uuid

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

from agent.memory import (  # noqa: E402
    EstadoConversacion,
    EventoEntrante,
    HandoffTicket,
    Mensaje,
    cancelar_seguimientos_compra,
    conversacion_pausada,
    crear_handoff,
    finalizar_seguimiento_compra,
    inicializar_db,
    listar_handoffs,
    programar_seguimiento_compra,
    purgar_datos_antiguos,
    reclamar_seguimientos_vencidos,
    resolver_handoff,
    seguimiento_compra_activo,
)


class HandoffPersistenciaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await inicializar_db()

    async def test_crear_pausar_resolver_y_reactivar(self):
        sufijo = uuid.uuid4().hex
        conversacion = f"whatsapp:569{sufijo[:8]}"
        ticket = await crear_handoff(
            conversacion,
            "whatsapp",
            "56900000000",
            "pedido_asistido",
            "No sé comprar, háganme el pedido",
        )

        self.assertTrue(await conversacion_pausada(conversacion))
        pendientes = await listar_handoffs("pendiente")
        self.assertTrue(any(item["id"] == ticket["id"] for item in pendientes))

        self.assertTrue(await resolver_handoff(ticket["id"]))
        self.assertFalse(await conversacion_pausada(conversacion))
        self.assertFalse(await resolver_handoff(ticket["id"]))

    async def test_fechas_con_zona_horaria_y_purga_compatible_con_postgres(self):
        columnas = [
            Mensaje.__table__.c.timestamp,
            EventoEntrante.__table__.c.timestamp,
            EstadoConversacion.__table__.c.actualizado,
            HandoffTicket.__table__.c.creado,
            HandoffTicket.__table__.c.actualizado,
        ]

        self.assertTrue(all(columna.type.timezone for columna in columnas))
        await purgar_datos_antiguos(90)

    async def test_seguimiento_se_programa_reclama_y_finaliza_una_sola_vez(self):
        conversacion = f"messenger:{uuid.uuid4().hex}"
        creado = await programar_seguimiento_compra(
            conversacion,
            "messenger",
            "cliente-prueba",
            "Antena Digital Full HD 4K",
            minutos=0,
        )

        vencidos = await reclamar_seguimientos_vencidos()
        seguimiento = next(item for item in vencidos if item["id"] == creado["id"])
        self.assertEqual(seguimiento["estado"], "procesando")
        self.assertTrue(await seguimiento_compra_activo(creado["id"]))

        await finalizar_seguimiento_compra(creado["id"], True)
        self.assertFalse(await seguimiento_compra_activo(creado["id"]))
        segunda_revision = await reclamar_seguimientos_vencidos()
        self.assertFalse(any(item["id"] == creado["id"] for item in segunda_revision))

    async def test_respuesta_del_cliente_cancela_el_seguimiento(self):
        conversacion = f"instagram:{uuid.uuid4().hex}"
        creado = await programar_seguimiento_compra(
            conversacion,
            "instagram",
            "cliente-prueba",
            "Cabezal de ducha",
            minutos=0,
        )

        self.assertEqual(await cancelar_seguimientos_compra(conversacion), 1)
        vencidos = await reclamar_seguimientos_vencidos()
        self.assertFalse(any(item["id"] == creado["id"] for item in vencidos))


if __name__ == "__main__":
    unittest.main()
