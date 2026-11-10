"""Pantallas de trabajos. Interfaz tonta: llama a las mismas funciones que la línea de órdenes."""
import uuid
from datetime import timezone
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from alfred.nucleo.datos.modelos import Trabajo
from alfred.nucleo.minijobs.registro import descubrir
from alfred.nucleo.trabajos.estados import ACTIVOS, ETIQUETAS, Estado
from alfred.nucleo.trabajos.servicio import TransicionInvalida, reintentar, solicitar_cancelacion
from alfred.nucleo.zona_temporal.limpieza import caduca_en, horas_conservacion

LIMITE_LISTA = 50


def fecha(momento) -> str:
    if momento is None:
        return "—"
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.astimezone().strftime("%d/%m/%Y %H:%M:%S")


def crear_router(sesiones, zona: Path, horas_defecto: float, plantillas, contexto) -> APIRouter:
    router = APIRouter()
    plantillas.env.filters["fecha"] = fecha

    def minijobs() -> dict:
        return {m.id: m for m in descubrir()[0]}

    @router.get("/trabajos", response_class=HTMLResponse)
    def lista(request: Request):
        with sesiones() as s:
            trabajos = s.scalars(select(Trabajo).order_by(Trabajo.creado_en.desc())
                                 .limit(LIMITE_LISTA)).all()
        catalogo = minijobs()
        nombres = {t.minijob_id: catalogo[t.minijob_id].nombre if t.minijob_id in catalogo else t.minijob_id
                   for t in trabajos}
        return plantillas.TemplateResponse(request, "trabajos.html", contexto(
            request, trabajos=trabajos, nombres=nombres, etiquetas=ETIQUETAS,
            hay_activos=any(t.estado in ACTIVOS for t in trabajos)))

    @router.get("/trabajos/{trabajo_id}", response_class=HTMLResponse)
    def detalle(request: Request, trabajo_id: uuid.UUID):
        with sesiones() as s:
            trabajo = s.get(Trabajo, trabajo_id)
        if trabajo is None:
            return HTMLResponse("Trabajo no encontrado", status_code=404)
        catalogo = minijobs()
        nombre = catalogo[trabajo.minijob_id].nombre if trabajo.minijob_id in catalogo else trabajo.minijob_id
        horas = horas_conservacion(trabajo, catalogo, horas_defecto)
        return plantillas.TemplateResponse(request, "trabajo.html", contexto(
            request, t=trabajo, nombre_minijob=nombre, etiquetas=ETIQUETAS,
            hay_activos=trabajo.estado in ACTIVOS, caduca=caduca_en(trabajo, horas),
            puede_cancelar=trabajo.estado in (Estado.PENDIENTE.value, Estado.EN_CURSO.value),
            puede_reintentar=(trabajo.estado == Estado.INTERRUMPIDO.value
                              and trabajo.ficheros_eliminados_en is None)))

    def _accion(trabajo_id: uuid.UUID, hacer):
        with sesiones() as s:
            trabajo = s.get(Trabajo, trabajo_id, with_for_update=True)
            if trabajo is None:
                return HTMLResponse("Trabajo no encontrado", status_code=404)
            try:
                hacer(s, trabajo)
                s.commit()
            except TransicionInvalida:
                s.rollback()  # p. ej. ya terminó: simplemente se muestra su estado actual
        return RedirectResponse(f"/trabajos/{trabajo_id}", status_code=303)

    @router.post("/trabajos/{trabajo_id}/cancelar")
    def cancelar(trabajo_id: uuid.UUID):
        return _accion(trabajo_id, lambda s, t: solicitar_cancelacion(s, t, zona))

    @router.post("/trabajos/{trabajo_id}/reintentar")
    def reintentar_trabajo(trabajo_id: uuid.UUID):
        return _accion(trabajo_id, lambda s, t: reintentar(s, t))

    return router
