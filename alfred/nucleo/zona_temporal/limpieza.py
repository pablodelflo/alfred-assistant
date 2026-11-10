"""Limpieza por caducidad de los ficheros de los trabajos.

Se borra la carpeta del trabajo; la fila del historial se conserva siempre.
"""
import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from alfred.nucleo.actividad.registro import registrar
from alfred.nucleo.datos.modelos import Trabajo
from alfred.nucleo.minijobs import registro
from alfred.nucleo.trabajos.estados import Estado
from alfred.nucleo.zona_temporal.rutas import borrar, carpeta_trabajo

log = logging.getLogger("alfred.limpieza")

# Estados que conservan ficheros hasta que caducan (interrumpido: para poder reintentar).
CON_FICHEROS = (Estado.TERMINADO.value, Estado.TERMINADO_CON_AVISOS.value,
                Estado.FALLIDO.value, Estado.INTERRUMPIDO.value)
MARGEN_HUERFANAS_S = 3600  # no se tocan carpetas recientes (p. ej. una subida aún sin trabajo)


def _utc(momento: datetime) -> datetime:
    return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)


def horas_conservacion(trabajo: Trabajo, minijobs: dict, defecto: float) -> float:
    minijob = minijobs.get(trabajo.minijob_id)
    if minijob is not None and minijob.conservacion_horas is not None:
        return minijob.conservacion_horas
    return defecto


def caduca_en(trabajo: Trabajo, horas: float) -> datetime | None:
    """Cuándo caducan los ficheros del trabajo; None si no caducan o aún no aplica."""
    if horas == 0 or trabajo.estado not in CON_FICHEROS or trabajo.terminado_en is None:
        return None
    return _utc(trabajo.terminado_en) + timedelta(hours=horas)


def limpiar(sesiones: sessionmaker[Session], zona: Path, horas_defecto: float, *,
            ahora: datetime | None = None) -> int:
    """Devuelve cuántas carpetas se eliminaron."""
    ahora = ahora or datetime.now(timezone.utc)
    minijobs = {m.id: m for m in registro.descubrir()[0]}
    eliminadas = 0

    with sesiones() as s:
        candidatos = s.scalars(select(Trabajo.id).where(
            Trabajo.estado.in_(CON_FICHEROS), Trabajo.ficheros_eliminados_en.is_(None),
            Trabajo.terminado_en.is_not(None))).all()
    for trabajo_id in candidatos:
        with sesiones() as s:
            trabajo = s.get(Trabajo, trabajo_id, with_for_update=True)
            if (trabajo is None or trabajo.estado not in CON_FICHEROS
                    or trabajo.ficheros_eliminados_en is not None):
                continue  # cambió mientras tanto (p. ej. se reintentó)
            limite = caduca_en(trabajo, horas_conservacion(trabajo, minijobs, horas_defecto))
            if limite is None or ahora < limite:
                continue
            borrar(carpeta_trabajo(zona, trabajo.id))
            trabajo.ficheros_eliminados_en = ahora
            registrar(s, "zona_temporal.limpieza",
                      f"Ficheros del trabajo {str(trabajo.id)[:8]} eliminados por caducidad",
                      trabajo_id=trabajo.id)
            s.commit()
            eliminadas += 1
    return eliminadas + _limpiar_huerfanas(sesiones, zona, ahora)


def _limpiar_huerfanas(sesiones, zona: Path, ahora: datetime) -> int:
    """Carpetas de trabajos que ya no existen, cancelados o ya limpiados (restos de un fallo)."""
    if not zona.is_dir():
        return 0
    eliminadas = 0
    for carpeta in zona.iterdir():
        if not carpeta.is_dir():
            continue
        try:
            trabajo_id = uuid.UUID(carpeta.name)
        except ValueError:
            continue  # no es de Alfred: no se toca
        if ahora.timestamp() - carpeta.stat().st_mtime < MARGEN_HUERFANAS_S:
            continue
        with sesiones() as s:
            trabajo = s.get(Trabajo, trabajo_id)
            huerfana = (trabajo is None or trabajo.estado == Estado.CANCELADO.value
                        or trabajo.ficheros_eliminados_en is not None)
            if huerfana:
                borrar(carpeta)
                registrar(s, "zona_temporal.huerfana", f"Carpeta huérfana {carpeta.name[:8]} eliminada",
                          detalle={"carpeta": carpeta.name}, trabajo_id=trabajo.id if trabajo else None)
                s.commit()
                eliminadas += 1
    return eliminadas


class Limpiador:
    """Hilo que ejecuta la limpieza al arrancar y luego cada cierto tiempo."""

    def __init__(self, sesiones, zona: Path, horas_defecto: float, cada_minutos: float = 10.0):
        self._sesiones, self._zona, self._horas = sesiones, zona, horas_defecto
        self._cada_s = cada_minutos * 60
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None

    def start(self) -> None:
        self._parar.clear()
        self._hilo = threading.Thread(target=self._bucle, name="limpiador", daemon=True)
        self._hilo.start()

    def stop(self) -> None:
        self._parar.set()
        if self._hilo:
            self._hilo.join(timeout=5)

    def _bucle(self) -> None:
        while not self._parar.is_set():
            try:
                limpiar(self._sesiones, self._zona, self._horas)
            except Exception:
                log.exception("Error en la limpieza de la zona temporal")
            self._parar.wait(self._cada_s)
