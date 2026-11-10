"""Operaciones sobre trabajos. Es el único sitio que cambia estados."""
from pathlib import Path

from sqlalchemy.orm import Session

from alfred.nucleo.actividad.registro import registrar
from alfred.nucleo.datos.modelos import Trabajo, ahora
from alfred.nucleo.trabajos.estados import Estado, es_final, transicion_valida
from alfred.nucleo.zona_temporal.rutas import borrar, carpeta_trabajo


class TransicionInvalida(Exception):
    pass


def crear_trabajo(sesion: Session, minijob_id: str, entradas: dict | None = None) -> Trabajo:
    trabajo = Trabajo(minijob_id=minijob_id, entradas=entradas or {},
                      estado=Estado.PENDIENTE.value)
    sesion.add(trabajo)
    sesion.flush()  # asigna el id
    registrar(sesion, "trabajo.creado", f"Trabajo de {minijob_id} creado", trabajo_id=trabajo.id)
    return trabajo


def cambiar_estado(sesion: Session, trabajo: Trabajo, destino: Estado, *,
                   error_usuario: str | None = None, error_tecnico: str | None = None) -> None:
    """Valida la transición, actualiza marcas de tiempo y deja rastro en la actividad.

    No hace commit: lo decide quien llama.
    """
    origen = Estado(trabajo.estado)
    if not transicion_valida(origen, destino):
        raise TransicionInvalida(f"{origen.value} -> {destino.value} no está permitido")

    trabajo.estado = destino.value
    if destino is Estado.EN_CURSO:
        trabajo.iniciado_en = ahora()
        trabajo.terminado_en = None
    if destino is Estado.PENDIENTE:  # reintento tras interrupción
        trabajo.iniciado_en = None
        trabajo.terminado_en = None
        trabajo.progreso = 0
        trabajo.mensaje_progreso = None
    if es_final(destino) or destino is Estado.INTERRUMPIDO:
        trabajo.terminado_en = ahora()
    if error_usuario is not None:
        trabajo.error_usuario = error_usuario
    if error_tecnico is not None:
        trabajo.error_tecnico = error_tecnico

    registrar(sesion, "trabajo.estado", f"{origen.value} -> {destino.value}",
              detalle={"origen": origen.value, "destino": destino.value},
              trabajo_id=trabajo.id)
    sesion.flush()


def solicitar_cancelacion(sesion: Session, trabajo: Trabajo, zona_temporal: Path) -> None:
    """Pendiente: se cancela ya. En curso: pasa a «cancelándose» y el lanzador detiene el proceso."""
    estado = Estado(trabajo.estado)
    if estado is Estado.CANCELANDOSE:
        return
    if estado is Estado.PENDIENTE:
        cambiar_estado(sesion, trabajo, Estado.CANCELADO)
        borrar(carpeta_trabajo(zona_temporal, trabajo.id))
    else:
        cambiar_estado(sesion, trabajo, Estado.CANCELANDOSE)


def reintentar(sesion: Session, trabajo: Trabajo) -> None:
    """Solo los trabajos interrumpidos se pueden reintentar, y solo si conservan sus ficheros."""
    if trabajo.ficheros_eliminados_en is not None:
        raise TransicionInvalida("Los ficheros del trabajo ya se eliminaron: crea uno nuevo")
    cambiar_estado(sesion, trabajo, Estado.PENDIENTE)
