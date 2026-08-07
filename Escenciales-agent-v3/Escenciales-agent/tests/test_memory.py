import os
import unittest
import uuid

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

from agent.memory import (  # noqa: E402
    EstadoConversacion,
    EventoEntrante,
    HandoffTicket,
    Mensaje,
    conversacion_pausada,
    crear_handoff,
    inicializar_db,
    listar_handoffs,
    purgar_datos_antiguos,
    resolver_handoff,
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


if __name__ == "__main__":
    unittest.main()
