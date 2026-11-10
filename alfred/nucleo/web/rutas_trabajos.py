"""Pantallas de trabajos y descarga de resultados. Interfaz tonta: usa las mismas funciones que la terminal."""
import uuid
from datetime import timezone

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy import select

from alfred.nucleo.datos.modelos import Trabajo
from alfred.nucleo.minijobs.registro import descubrir
from alfred.nucleo.trabajos.estados import ACTIVOS, ETIQUETAS, Estado
from alfred.nucleo.trabajos.servicio import TransicionInvalida, reintentar, solicitar_cancelacion
from alfred.nucleo.zona_temporal.limpieza import caduca_en, horas_conservacion
from alfred.nucleo.zona_temporal.rutas import carpeta_trabajo, crear_zip, listar_salida, ruta_segura

LIMITE_LISTA = 50
CON_RESULTADOS = (Estado.TERMINADO.value, Estado.TERMINADO_CON_AVISOS.value)


def fecha(momento) -> str:
    if momento is None:
        return "—"
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.astimezone().strftime("%d/%m/%Y %H:%M:%S")


def tamano(n: int) -> str:
    for unidad in ("B", "KB", "MB", "GB"):
        if n < 1024 or unidad == "GB":
            return f"{n} B" if unidad == "B" else f"{n:.1f} {unidad}"
        n /= 1024


def crear_router(sesiones, config, plantillas, contexto) -> APIRouter:
    router = APIRouter()
    plantillas.env.filters["fecha"] = fecha
    plantillas.env.filters["tamano"] = tamano

    def minijobs() -> dict:
        return {m.id: m for m in descubrir()[0]}

    def zona():
        return config.zona_temporal.resolve()

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

    def _con_resultados(trabajo) -> bool:
        return trabajo is not None and trabajo.estado in CON_RESULTADOS and trabajo.ficheros_eliminados_en is None

    @router.get("/trabajos/{trabajo_id}", response_class=HTMLResponse)
    def detalle(request: Request, trabajo_id: uuid.UUID):
        with sesiones() as s:
            trabajo = s.get(Trabajo, trabajo_id)
        if trabajo is None:
            return HTMLResponse("Trabajo no encontrado", status_code=404)
        catalogo = minijobs()
        nombre = catalogo[trabajo.minijob_id].nombre if trabajo.minijob_id in catalogo else trabajo.minijob_id
        horas = horas_conservacion(trabajo, catalogo, config.conservacion_horas)
        ficheros = listar_salida(carpeta_trabajo(zona(), trabajo.id)) if _con_resultados(trabajo) else []
        return plantillas.TemplateResponse(request, "trabajo.html", contexto(
            request, t=trabajo, nombre_minijob=nombre, etiquetas=ETIQUETAS,
            hay_activos=trabajo.estado in ACTIVOS, caduca=caduca_en(trabajo, horas), ficheros=ficheros,
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
        return _accion(trabajo_id, lambda s, t: solicitar_cancelacion(s, t, zona()))

    @router.post("/trabajos/{trabajo_id}/reintentar")
    def reintentar_trabajo(trabajo_id: uuid.UUID):
        return _accion(trabajo_id, lambda s, t: reintentar(s, t))

    # ---- descargas ----
    def _trabajo_descargable(trabajo_id: uuid.UUID):
        with sesiones() as s:
            trabajo = s.get(Trabajo, trabajo_id)
        return trabajo if _con_resultados(trabajo) else None

    @router.get("/trabajos/{trabajo_id}/resultado.zip")
    def descargar_zip(trabajo_id: uuid.UUID):
        if _trabajo_descargable(trabajo_id) is None:
            return HTMLResponse("No hay resultados disponibles para este trabajo", status_code=404)
        carpeta = carpeta_trabajo(zona(), trabajo_id)
        if not listar_salida(carpeta):
            return HTMLResponse("No hay resultados disponibles para este trabajo", status_code=404)
        return FileResponse(crear_zip(carpeta), media_type="application/zip",
                            filename=f"alfred-{str(trabajo_id)[:8]}.zip")

    @router.get("/trabajos/{trabajo_id}/ficheros/{ruta:path}")
    def descargar_fichero(trabajo_id: uuid.UUID, ruta: str):
        if _trabajo_descargable(trabajo_id) is None:
            return HTMLResponse("No hay resultados disponibles para este trabajo", status_code=404)
        destino = ruta_segura(carpeta_trabajo(zona(), trabajo_id) / "salida", ruta)
        if destino is None or not destino.is_file():
            return HTMLResponse("Fichero no encontrado", status_code=404)
        return FileResponse(destino, filename=destino.name)

    return router
