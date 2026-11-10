"""Tras un reinicio: los trabajos en curso pasan a interrumpido y se eliminan procesos huérfanos."""
import os
import signal
from pathlib import Path

from sqlalchemy import select

from alfred.nucleo.datos.modelos import Trabajo
from alfred.nucleo.trabajos.estados import Estado
from alfred.nucleo.trabajos.servicio import cambiar_estado

MARCA_PROCESO = "alfred.nucleo.trabajos.proceso"


def es_proceso_de_trabajo(pid: int) -> bool:
    """Evita matar un proceso ajeno si el PID se reutilizó."""
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        return False
    return MARCA_PROCESO in cmdline


def _matar_huerfano(pid: int) -> None:
    try:
        if es_proceso_de_trabajo(pid) and os.getpgid(pid) == pid:
            os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def recuperar(sesiones) -> int:
    """Devuelve cuántos trabajos se marcaron como interrumpidos."""
    with sesiones() as s:
        trabajos = s.scalars(
            select(Trabajo).where(Trabajo.estado.in_(
                [Estado.EN_CURSO.value, Estado.CANCELANDOSE.value])).with_for_update()).all()
        for trabajo in trabajos:
            if trabajo.pid:
                _matar_huerfano(trabajo.pid)
            trabajo.pid = None
            cambiar_estado(s, trabajo, Estado.INTERRUMPIDO,
                           error_usuario="Alfred se reinició mientras se ejecutaba el trabajo.")
        s.commit()
        return len(trabajos)
