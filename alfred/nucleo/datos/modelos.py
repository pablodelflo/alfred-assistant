"""Modelos de datos: trabajos y registro de actividad."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from alfred.nucleo.datos.base import Base
from alfred.nucleo.trabajos.estados import Estado


def ahora() -> datetime:
    return datetime.now(timezone.utc)


class Trabajo(Base):
    __tablename__ = "trabajos"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    minijob_id: Mapped[str] = mapped_column(String(100), index=True)
    estado: Mapped[str] = mapped_column(String(30), default=Estado.PENDIENTE.value, index=True)
    entradas: Mapped[dict] = mapped_column(JSON, default=dict)
    progreso: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    mensaje_progreso: Mapped[str | None] = mapped_column(String(300))
    pid: Mapped[int | None] = mapped_column(Integer)  # proceso de trabajo en ejecución
    informe: Mapped[dict | None] = mapped_column(JSON)  # resultados, resumen, fallos parciales
    error_usuario: Mapped[str | None] = mapped_column(Text)  # mensaje claro
    error_tecnico: Mapped[str | None] = mapped_column(Text)  # detalle para el log
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
    iniciado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ficheros_eliminados_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Actividad(Base):
    """Registro de acciones y errores. Se conserva indefinidamente."""

    __tablename__ = "actividad"
    __table_args__ = (Index("ix_actividad_momento", "momento"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    momento: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
    tipo: Mapped[str] = mapped_column(String(50))  # p. ej. "trabajo.estado", "sistema.arranque"
    mensaje: Mapped[str] = mapped_column(Text)
    detalle: Mapped[dict | None] = mapped_column(JSON)
    trabajo_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("trabajos.id", ondelete="SET NULL"), index=True
    )


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(100), unique=True)  # en minúsculas
    clave_hash: Mapped[str] = mapped_column(String(300))
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
    ultimo_acceso: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Sesion(Base):
    """Sesión web. Se guarda el hash del token, nunca el token."""

    __tablename__ = "sesiones"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), index=True)
    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
    expira_en: Mapped[datetime] = mapped_column(DateTime(timezone=True))
