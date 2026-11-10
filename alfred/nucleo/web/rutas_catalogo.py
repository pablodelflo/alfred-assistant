"""Formulario generado desde el manifiesto del minijob y lanzamiento de trabajos."""
import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.exceptions import HTTPException as ErrorHTTP

from alfred.nucleo.minijobs.entradas import validar
from alfred.nucleo.minijobs.registro import descubrir
from alfred.nucleo.trabajos.servicio import crear_trabajo
from alfred.nucleo.zona_temporal.rutas import borrar, carpeta_trabajo
from alfred.nucleo.zona_temporal.subidas import MB, ErrorSubida, espacio_libre, guardar_subidas

MARGEN_FRAMING = MB  # el cuerpo multipart pesa algo más que los ficheros


def crear_router(sesiones, config, plantillas, contexto) -> APIRouter:
    router = APIRouter()

    def buscar(minijob_id: str):
        return {m.id: m for m in descubrir()[0]}.get(minijob_id)

    def formulario(request: Request, minijob, *, valores=None, errores=None, error_general=None, estado=200):
        return plantillas.TemplateResponse(request, "minijob.html", contexto(
            request, m=minijob, valores=valores or {}, errores=errores or {}, error_general=error_general,
            max_fichero_mb=config.max_fichero_mb, max_lote_mb=config.max_lote_mb,
            max_ficheros=config.max_ficheros), status_code=estado)

    @router.get("/catalogo/{minijob_id}", response_class=HTMLResponse)
    def ver(request: Request, minijob_id: str):
        minijob = buscar(minijob_id)
        if minijob is None:
            return HTMLResponse("Minijob no encontrado", status_code=404)
        return formulario(request, minijob)

    @router.post("/catalogo/{minijob_id}/lanzar")
    async def lanzar(request: Request, minijob_id: str):
        minijob = buscar(minijob_id)
        if minijob is None:
            return HTMLResponse("Minijob no encontrado", status_code=404)
        if not minijob.disponible:
            return formulario(request, minijob, error_general="Este minijob no está disponible.", estado=400)

        zona = config.zona_temporal.resolve()
        declarado = int(request.headers.get("content-length") or 0)
        if declarado > config.max_lote_mb * MB + MARGEN_FRAMING:
            return formulario(request, minijob, estado=413,
                              error_general=f"La subida supera el máximo por lote ({config.max_lote_mb:g} MB).")
        if declarado * 2 > espacio_libre(zona):  # se escribe dos veces: temporal del servidor + carpeta del trabajo
            return formulario(request, minijob, estado=507,
                              error_general="No hay espacio suficiente en el servidor para esta subida.")

        campo_ficheros = next((c for c in minijob.entradas if c.tipo == "ficheros"), None)
        try:
            async with request.form(max_files=config.max_ficheros + 1, max_fields=200) as form:
                enviado = {k: v for k, v in form.items() if isinstance(v, str)}
                validacion = validar(minijob.entradas, enviado)
                archivos = []
                if campo_ficheros:
                    archivos = [(u.filename, u.file) for u in form.getlist(campo_ficheros.id)
                                if getattr(u, "filename", None)]
                    if not archivos and campo_ficheros.obligatorio:
                        validacion.errores[campo_ficheros.id] = "Elige al menos un fichero"
                if not validacion.ok:
                    return formulario(request, minijob, valores=enviado, errores=validacion.errores, estado=422)

                def guardar():
                    with sesiones() as s:
                        trabajo = crear_trabajo(s, minijob.id, dict(validacion.valores))
                        carpeta = carpeta_trabajo(zona, trabajo.id)
                        try:
                            if campo_ficheros:
                                nombres, ignorados = guardar_subidas(
                                    archivos, carpeta / "entrada", max_fichero_mb=config.max_fichero_mb,
                                    max_lote_mb=config.max_lote_mb, max_ficheros=config.max_ficheros,
                                    extensiones=campo_ficheros.extensiones)
                                trabajo.entradas = {**trabajo.entradas, "ficheros": nombres,
                                                    "ficheros_ignorados": ignorados}
                                if not nombres and campo_ficheros.obligatorio:
                                    raise ErrorSubida("Ninguno de los ficheros elegidos es de un tipo admitido "
                                                      f"({', '.join(campo_ficheros.extensiones)}).")
                            s.commit()  # el trabajo solo existe cuando sus ficheros ya están en disco
                        except BaseException:
                            s.rollback()
                            borrar(carpeta)
                            raise
                        return trabajo.id

                try:
                    trabajo_id = await asyncio.to_thread(guardar)
                except ErrorSubida as e:
                    return formulario(request, minijob, valores=enviado, error_general=str(e), estado=413)
        except ErrorHTTP as e:  # p. ej. demasiados ficheros según el analizador multipart
            return formulario(request, minijob, estado=400,
                              error_general=f"No se pudo leer la subida: {e.detail}")
        return RedirectResponse(f"/trabajos/{trabajo_id}", status_code=303)

    return router
