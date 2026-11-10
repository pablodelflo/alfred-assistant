"""Aplicación web: interfaz tonta; las decisiones viven en el núcleo."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
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


def crear_app(*servicios, sesiones=None, zona_temporal: Path | None = None,
              conservacion_horas: float = 6.0) -> FastAPI:
    """`servicios`: objetos con start()/stop() que viven mientras vive la app (lanzador, limpiador).

    Si se pasan `sesiones` y `zona_temporal`, se activan las pantallas de trabajos.
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

    if sesiones is not None and zona_temporal is not None:
        from alfred.nucleo.web.rutas_trabajos import crear_router
        app.include_router(crear_router(sesiones, zona_temporal, conservacion_horas, PLANTILLAS, contexto))

    return app
