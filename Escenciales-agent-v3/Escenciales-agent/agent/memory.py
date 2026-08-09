import os
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Text, DateTime, select, Integer, delete, update
from sqlalchemy.exc import IntegrityError
from dotenv import load_dotenv

load_dotenv()

def normalizar_url_bd(valor: str | None) -> str:
    """Normaliza la URL de Railway y mantiene el agente disponible en desarrollo.

    Railway puede entregar una variable aún vacía mientras se aplica una referencia
    entre servicios. En ese caso usamos /tmp, que es escribible por el usuario no
    privilegiado del contenedor. La memoria temporal se reemplaza automáticamente
    cuando exista una URL PostgreSQL válida.
    """
    url = (valor or "").strip().strip('"').strip("'")
    if url.startswith("DATABASE_URL="):
        url = url.split("=", 1)[1].strip()
    if not url or url.startswith("${{"):
        return "sqlite+aiosqlite:////tmp/escenciales.db"
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


DATABASE_URL = normalizar_url_bd(os.getenv("DATABASE_URL"))

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Mensaje(Base):
    __tablename__ = "mensajes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telefono: Mapped[str] = mapped_column(String(50), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class EventoEntrante(Base):
    __tablename__ = "eventos_entrantes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mensaje_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class EstadoConversacion(Base):
    __tablename__ = "estados_conversacion"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversacion_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    estado: Mapped[str] = mapped_column(String(30), default="bot_activo")
    motivo: Mapped[str | None] = mapped_column(String(100), nullable=True)
    actualizado: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class HandoffTicket(Base):
    __tablename__ = "handoff_tickets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversacion_id: Mapped[str] = mapped_column(String(255), index=True)
    canal: Mapped[str] = mapped_column(String(30))
    contacto: Mapped[str] = mapped_column(String(255))
    motivo: Mapped[str] = mapped_column(String(100))
    resumen: Mapped[str] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(String(30), default="pendiente", index=True)
    creado: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    actualizado: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class SeguimientoCompra(Base):
    __tablename__ = "seguimientos_compra"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversacion_id: Mapped[str] = mapped_column(String(255), index=True)
    canal: Mapped[str] = mapped_column(String(30))
    contacto: Mapped[str] = mapped_column(String(255))
    producto: Mapped[str] = mapped_column(String(150))
    estado: Mapped[str] = mapped_column(String(30), default="pendiente", index=True)
    intentos: Mapped[int] = mapped_column(Integer, default=0)
    enviar_despues: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    creado: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    actualizado: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


async def inicializar_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def guardar_mensaje(telefono: str, role: str, content: str):
    async with async_session() as session:
        mensaje = Mensaje(
            telefono=telefono,
            role=role,
            content=content,
            timestamp=datetime.now(timezone.utc)
        )
        session.add(mensaje)
        await session.commit()


async def obtener_historial(telefono: str, limite: int = 20) -> list[dict]:
    async with async_session() as session:
        query = (
            select(Mensaje)
            .where(Mensaje.telefono == telefono)
            .order_by(Mensaje.timestamp.desc())
            .limit(limite)
        )
        result = await session.execute(query)
        mensajes = result.scalars().all()
        mensajes.reverse()

        return [
            {"role": msg.role, "content": msg.content}
            for msg in mensajes
        ]


async def limpiar_historial(telefono: str):
    async with async_session() as session:
        query = select(Mensaje).where(Mensaje.telefono == telefono)
        result = await session.execute(query)
        mensajes = result.scalars().all()
        for msg in mensajes:
            await session.delete(msg)
        await session.commit()


def _seguimiento_dict(seguimiento: SeguimientoCompra) -> dict:
    return {
        "id": seguimiento.id,
        "conversacion_id": seguimiento.conversacion_id,
        "canal": seguimiento.canal,
        "contacto": seguimiento.contacto,
        "producto": seguimiento.producto,
        "estado": seguimiento.estado,
        "intentos": seguimiento.intentos,
        "enviar_despues": seguimiento.enviar_despues,
    }


async def programar_seguimiento_compra(
    conversacion_id: str,
    canal: str,
    contacto: str,
    producto: str,
    minutos: float = 15,
) -> dict:
    """Programa un solo recordatorio tras enviar el checkout."""
    ahora = datetime.now(timezone.utc)
    async with async_session() as session:
        await session.execute(
            update(SeguimientoCompra)
            .where(SeguimientoCompra.conversacion_id == conversacion_id)
            .where(SeguimientoCompra.estado.in_(("pendiente", "procesando")))
            .values(estado="cancelado", actualizado=ahora)
        )
        seguimiento = SeguimientoCompra(
            id=str(uuid.uuid4()),
            conversacion_id=conversacion_id,
            canal=canal,
            contacto=contacto,
            producto=producto,
            estado="pendiente",
            intentos=0,
            enviar_despues=ahora + timedelta(minutes=max(0, minutos)),
            creado=ahora,
            actualizado=ahora,
        )
        session.add(seguimiento)
        await session.commit()
        return _seguimiento_dict(seguimiento)


async def cancelar_seguimientos_compra(conversacion_id: str) -> int:
    """Cancela recordatorios cuando responde el cliente o interviene el equipo."""
    ahora = datetime.now(timezone.utc)
    async with async_session() as session:
        resultado = await session.execute(
            update(SeguimientoCompra)
            .where(SeguimientoCompra.conversacion_id == conversacion_id)
            .where(SeguimientoCompra.estado.in_(("pendiente", "procesando")))
            .values(estado="cancelado", actualizado=ahora)
        )
        await session.commit()
        return int(resultado.rowcount or 0)


async def reclamar_seguimientos_vencidos(limite: int = 20) -> list[dict]:
    """Reserva recordatorios vencidos para evitar envíos duplicados."""
    ahora = datetime.now(timezone.utc)
    async with async_session() as session:
        await session.execute(
            update(SeguimientoCompra)
            .where(SeguimientoCompra.estado == "procesando")
            .where(SeguimientoCompra.actualizado < ahora - timedelta(minutes=10))
            .values(estado="pendiente", actualizado=ahora)
        )
        resultado = await session.execute(
            select(SeguimientoCompra)
            .where(SeguimientoCompra.estado == "pendiente")
            .where(SeguimientoCompra.enviar_despues <= ahora)
            .order_by(SeguimientoCompra.enviar_despues.asc())
            .limit(min(max(limite, 1), 100))
            .with_for_update(skip_locked=True)
        )
        seguimientos = list(resultado.scalars().all())
        for seguimiento in seguimientos:
            seguimiento.estado = "procesando"
            seguimiento.intentos += 1
            seguimiento.actualizado = ahora
        await session.commit()
        return [_seguimiento_dict(item) for item in seguimientos]


async def seguimiento_compra_activo(seguimiento_id: str) -> bool:
    async with async_session() as session:
        seguimiento = await session.get(SeguimientoCompra, seguimiento_id)
        return bool(seguimiento and seguimiento.estado == "procesando")


async def finalizar_seguimiento_compra(
    seguimiento_id: str,
    enviado: bool,
) -> None:
    ahora = datetime.now(timezone.utc)
    async with async_session() as session:
        seguimiento = await session.get(SeguimientoCompra, seguimiento_id)
        if not seguimiento or seguimiento.estado != "procesando":
            return
        if enviado:
            seguimiento.estado = "enviado"
        elif seguimiento.intentos < 3:
            seguimiento.estado = "pendiente"
            seguimiento.enviar_despues = ahora + timedelta(minutes=5)
        else:
            seguimiento.estado = "fallido"
        seguimiento.actualizado = ahora
        await session.commit()


async def conversacion_pausada(conversacion_id: str) -> bool:
    async with async_session() as session:
        result = await session.execute(
            select(EstadoConversacion).where(
                EstadoConversacion.conversacion_id == conversacion_id
            )
        )
        estado = result.scalar_one_or_none()
        return bool(estado and estado.estado == "esperando_humano")


async def crear_handoff(
    conversacion_id: str,
    canal: str,
    contacto: str,
    motivo: str,
    resumen: str,
) -> dict:
    ahora = datetime.now(timezone.utc)
    async with async_session() as session:
        existente = await session.execute(
            select(HandoffTicket)
            .where(HandoffTicket.conversacion_id == conversacion_id)
            .where(HandoffTicket.estado == "pendiente")
            .order_by(HandoffTicket.creado.desc())
        )
        ticket = existente.scalars().first()
        if ticket:
            ticket.resumen = resumen[:1000]
            ticket.actualizado = ahora
        else:
            ticket = HandoffTicket(
                id=str(uuid.uuid4()),
                conversacion_id=conversacion_id,
                canal=canal,
                contacto=contacto,
                motivo=motivo,
                resumen=resumen[:1000],
                estado="pendiente",
                creado=ahora,
                actualizado=ahora,
            )
            session.add(ticket)

        estado_result = await session.execute(
            select(EstadoConversacion).where(
                EstadoConversacion.conversacion_id == conversacion_id
            )
        )
        estado = estado_result.scalar_one_or_none()
        if estado:
            estado.estado = "esperando_humano"
            estado.motivo = motivo
            estado.actualizado = ahora
        else:
            session.add(EstadoConversacion(
                conversacion_id=conversacion_id,
                estado="esperando_humano",
                motivo=motivo,
                actualizado=ahora,
            ))
        await session.commit()
        return _ticket_dict(ticket)


def _ticket_dict(ticket: HandoffTicket) -> dict:
    return {
        "id": ticket.id,
        "conversacion_id": ticket.conversacion_id,
        "canal": ticket.canal,
        "contacto": ticket.contacto,
        "motivo": ticket.motivo,
        "resumen": ticket.resumen,
        "estado": ticket.estado,
        "creado": ticket.creado.isoformat() if ticket.creado else None,
        "actualizado": ticket.actualizado.isoformat() if ticket.actualizado else None,
    }


async def listar_handoffs(estado: str = "pendiente", limite: int = 100) -> list[dict]:
    async with async_session() as session:
        result = await session.execute(
            select(HandoffTicket)
            .where(HandoffTicket.estado == estado)
            .order_by(HandoffTicket.creado.desc())
            .limit(min(max(limite, 1), 200))
        )
        return [_ticket_dict(ticket) for ticket in result.scalars().all()]


async def resolver_handoff(ticket_id: str) -> bool:
    ahora = datetime.now(timezone.utc)
    async with async_session() as session:
        ticket = await session.get(HandoffTicket, ticket_id)
        if not ticket or ticket.estado != "pendiente":
            return False
        ticket.estado = "resuelto"
        ticket.actualizado = ahora

        result = await session.execute(
            select(EstadoConversacion).where(
                EstadoConversacion.conversacion_id == ticket.conversacion_id
            )
        )
        estado = result.scalar_one_or_none()
        if estado:
            estado.estado = "bot_activo"
            estado.motivo = None
            estado.actualizado = ahora
        await session.commit()
        return True


async def registrar_evento_si_nuevo(mensaje_id: str) -> bool:
    """Evita responder dos veces cuando Meta reintenta un webhook."""
    if not mensaje_id:
        return True
    async with async_session() as session:
        session.add(EventoEntrante(mensaje_id=mensaje_id))
        try:
            await session.commit()
            return True
        except IntegrityError:
            await session.rollback()
            return False


async def purgar_datos_antiguos(dias: int) -> None:
    if dias <= 0:
        return
    limite = datetime.now(timezone.utc) - timedelta(days=dias)
    async with async_session() as session:
        await session.execute(delete(Mensaje).where(Mensaje.timestamp < limite))
        await session.execute(
            delete(EventoEntrante).where(EventoEntrante.timestamp < limite)
        )
        await session.execute(
            delete(HandoffTicket)
            .where(HandoffTicket.actualizado < limite)
            .where(HandoffTicket.estado == "resuelto")
        )
        await session.execute(
            delete(SeguimientoCompra)
            .where(SeguimientoCompra.actualizado < limite)
            .where(
                SeguimientoCompra.estado.in_(
                    ("enviado", "cancelado", "fallido")
                )
            )
        )
        await session.commit()
