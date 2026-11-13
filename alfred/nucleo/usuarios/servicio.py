"""Usuarios y sesiones. Un único administrador por ahora; el modelo admite más."""
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from alfred.nucleo.actividad.registro import registrar
from alfred.nucleo.datos.modelos import Sesion, Usuario, ahora
from alfred.nucleo.usuarios import claves

MIN_CLAVE = 12


class ErrorUsuario(Exception):
    """Mensaje claro para quien administra."""


@dataclass(frozen=True)
class UsuarioActual:
    id: int
    nombre: str


def _utc(momento: datetime) -> datetime:
    return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def comprobar_clave(nombre: str, clave: str) -> None:
    if len(clave) < MIN_CLAVE:
        raise ErrorUsuario(f"La contraseña debe tener al menos {MIN_CLAVE} caracteres.")
    if clave.lower() == nombre.lower():
        raise ErrorUsuario("La contraseña no puede ser igual al nombre de usuario.")


def hay_usuarios(sesion: Session) -> bool:
    return sesion.scalar(select(func.count()).select_from(Usuario)) > 0


def crear_usuario(sesion: Session, nombre: str, clave: str) -> Usuario:
    nombre = nombre.strip().lower()
    if not nombre:
        raise ErrorUsuario("El nombre de usuario no puede estar vacío.")
    if hay_usuarios(sesion):
        raise ErrorUsuario("Ya existe un administrador. Para cambiar su contraseña usa «cambiar-clave».")
    comprobar_clave(nombre, clave)
    usuario = Usuario(nombre=nombre, clave_hash=claves.hashear(clave))
    sesion.add(usuario)
    sesion.flush()
    registrar(sesion, "seguridad.usuario_creado", f"Usuario «{nombre}» creado")
    return usuario


def cambiar_clave(sesion: Session, nombre: str, clave: str) -> int:
    """Cambia la contraseña y cierra todas las sesiones de ese usuario. Devuelve las cerradas."""
    usuario = sesion.scalar(select(Usuario).where(Usuario.nombre == nombre.strip().lower()))
    if usuario is None:
        raise ErrorUsuario(f"No existe el usuario «{nombre}».")
    comprobar_clave(usuario.nombre, clave)
    usuario.clave_hash = claves.hashear(clave)
    cerradas = sesion.execute(delete(Sesion).where(Sesion.usuario_id == usuario.id)).rowcount
    registrar(sesion, "seguridad.clave_cambiada", f"Contraseña de «{usuario.nombre}» cambiada")
    return cerradas


def verificar_credenciales(sesion: Session, nombre: str, clave: str) -> UsuarioActual | None:
    usuario = sesion.scalar(select(Usuario).where(Usuario.nombre == nombre.strip().lower()))
    if usuario is None:
        claves.verificar_falso(clave)
        return None
    if not claves.verificar(clave, usuario.clave_hash):
        return None
    usuario.ultimo_acceso = ahora()
    return UsuarioActual(usuario.id, usuario.nombre)


def crear_sesion(sesion: Session, usuario_id: int, dias: float) -> str:
    token = secrets.token_urlsafe(32)
    sesion.add(Sesion(token_hash=_hash_token(token), usuario_id=usuario_id,
                      expira_en=ahora() + timedelta(days=dias)))
    return token


def validar_sesion(sesion: Session, token: str) -> UsuarioActual | None:
    fila = sesion.get(Sesion, _hash_token(token))
    if fila is None:
        return None
    if _utc(fila.expira_en) <= ahora():
        sesion.delete(fila)
        return None
    usuario = sesion.get(Usuario, fila.usuario_id)
    return UsuarioActual(usuario.id, usuario.nombre) if usuario else None


def cerrar_sesion(sesion: Session, token: str) -> None:
    sesion.execute(delete(Sesion).where(Sesion.token_hash == _hash_token(token)))


def cerrar_todas(sesion: Session) -> int:
    return sesion.execute(delete(Sesion)).rowcount


def limpiar_sesiones_caducadas(sesion: Session, momento: datetime | None = None) -> int:
    return sesion.execute(delete(Sesion).where(Sesion.expira_en <= (momento or ahora()))).rowcount
