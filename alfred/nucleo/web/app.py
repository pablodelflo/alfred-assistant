"""Aplicación web: interfaz tonta; las decisiones viven en el núcleo."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from alfred.comun.version import NOMBRE, VERSION
from alfred.nucleo.minijobs.registro import descubrir

AQUI = Path(__file__).parent
RAIZ = AQUI.parents[2]  # raíz del repositorio
PLANTILLAS = Jinja2Templates(directory=AQUI / "plantillas")


def leer_aviso() -> str:
    ruta = RAIZ / "NOTICE"
    return ruta.read_text(encoding="utf-8") if ruta.is_file() else NOMBRE


def crear_app(*servicios, sesiones=None, config=None) -> FastAPI:
    """`servicios`: objetos con start()/stop() que viven mientras vive la app (lanzador, limpiador).

    Si se pasan `sesiones` y `config`, se activan el formulario de los minijobs y las pantallas
    de trabajos. Los valores de `config` se leen en cada petición, nunca se copian al arrancar.
    """
    @asynccontextmanager
    async def ciclo(_app: FastAPI):
        for servicio in servicios:
            servicio.start()
        try:
            yield
        finally:
            for servicio in reversed(servicios):
                await asyncio.to_thread(servicio.stop)

    app = FastAPI(title=NOMBRE, version=VERSION, lifespan=ciclo)
    app.mount("/estaticos", StaticFiles(directory=AQUI / "estaticos"), name="estaticos")

    def contexto(request: Request, **extra):
        return {"request": request, "nombre": NOMBRE, "version": VERSION,
                "aviso_corto": leer_aviso().splitlines()[1] if leer_aviso() else "", **extra}

    @app.get("/", response_class=HTMLResponse)
    def inicio(request: Request):
        minijobs, avisos = descubrir()
        return PLANTILLAS.TemplateResponse(
            request, "inicio.html", contexto(request, minijobs=minijobs, avisos=avisos))

    @app.get("/acerca-de", response_class=HTMLResponse)
    def acerca_de(request: Request):
        return PLANTILLAS.TemplateResponse(
            request, "acerca_de.html", contexto(request, aviso=leer_aviso()))

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return RedirectResponse("/estaticos/favicon.svg")

    if sesiones is not None and config is not None:
        from alfred.nucleo.web.rutas_catalogo import crear_router as router_catalogo
        from alfred.nucleo.web.rutas_trabajos import crear_router as router_trabajos
        app.include_router(router_catalogo(sesiones, config, PLANTILLAS, contexto))
        app.include_router(router_trabajos(sesiones, config, PLANTILLAS, contexto))

    return app
