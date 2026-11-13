"""Acceso: pantalla de entrada, sesión por cookie y protección de todas las páginas.

Protección contra peticiones falsas entre sitios: cookie SameSite=Lax y comprobación de que
todo POST llega con un Origin (o Referer) del propio Alfred.
"""
import asyncio
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from alfred.nucleo.actividad.registro import registrar
from alfred.nucleo.usuarios import servicio
from alfred.nucleo.usuarios.limitador import LimitadorIntentos

COOKIE = "alfred_sesion"
METODOS_SEGUROS = ("GET", "HEAD", "OPTIONS")
RETRASO_FALLO_S = 0.5


def destino_seguro(siguiente: str | None) -> str:
    """Solo rutas internas: evita que /entrar?siguiente=... redirija a otro sitio."""
    if siguiente and siguiente.startswith("/") and not siguiente.startswith("//") and "\\" not in siguiente:
        return siguiente
    return "/"


def _con_sesion(sesiones, hacer):
    with sesiones() as s:
        resultado = hacer(s)
        s.commit()
        return resultado


def _origen_valido(request: Request, config) -> bool:
    origen = request.headers.get("origin") or request.headers.get("referer")
    if not origen or origen == "null":
        return False
    anfitrion = urlsplit(origen).netloc
    return anfitrion == request.headers.get("host", "") or anfitrion in config.origenes_permitidos


def instalar(app: FastAPI, sesiones, config, plantillas, contexto) -> None:
    limitador = LimitadorIntentos()

    def es_publica(ruta: str) -> bool:
        return ruta == "/entrar" or ruta == "/favicon.ico" or ruta.startswith("/estaticos/")

    @app.middleware("http")
    async def proteger(request: Request, siguiente):
        if request.method not in METODOS_SEGUROS and not _origen_valido(request, config):
            return PlainTextResponse("Petición rechazada: origen no permitido.", status_code=403)
        token = request.cookies.get(COOKIE)
        request.state.usuario = (
            await run_in_threadpool(_con_sesion, sesiones, lambda s: servicio.validar_sesion(s, token))
            if token else None)
        if request.state.usuario is None and not es_publica(request.url.path):
            destino = "/entrar"
            if request.method == "GET":
                destino += "?siguiente=" + quote(request.url.path + (f"?{request.url.query}" if request.url.query else ""), safe="")
            respuesta = RedirectResponse(destino, status_code=303)
            if token:
                respuesta.delete_cookie(COOKIE, path="/")  # sesión caducada o cerrada
            return respuesta
        return await siguiente(request)

    def pagina_entrada(request: Request, *, siguiente="/", error=None, estado=200, sin_admin=False):
        return plantillas.TemplateResponse(request, "entrar.html", contexto(
            request, siguiente=siguiente, error=error, sin_admin=sin_admin), status_code=estado)

    @app.get("/entrar", response_class=HTMLResponse)
    async def entrar(request: Request, siguiente: str = "/"):
        if request.state.usuario is not None:
            return RedirectResponse(destino_seguro(siguiente), status_code=303)
        hay = await run_in_threadpool(_con_sesion, sesiones, servicio.hay_usuarios)
        return pagina_entrada(request, siguiente=destino_seguro(siguiente), sin_admin=not hay)

    @app.post("/entrar")
    async def entrar_post(request: Request):
        datos = await request.form()
        nombre = str(datos.get("usuario", "")).strip()[:100]
        clave = str(datos.get("clave", ""))
        siguiente = destino_seguro(str(datos.get("siguiente", "/")))
        ip = request.client.host if request.client else "?"
        claves_limite = [f"ip:{ip}", f"usuario:{nombre.lower()}"]

        espera = limitador.segundos_de_bloqueo(claves_limite, config.intentos_max, config.bloqueo_minutos * 60)
        if espera:
            minutos = max(1, round(espera / 60))
            return pagina_entrada(request, siguiente=siguiente, estado=429,
                                  error=f"Demasiados intentos fallidos. Vuelve a intentarlo en unos {minutos} minuto(s).")

        usuario = await run_in_threadpool(
            _con_sesion, sesiones, lambda s: servicio.verificar_credenciales(s, nombre, clave))
        if usuario is None:
            limitador.fallo(claves_limite)
            await run_in_threadpool(_con_sesion, sesiones, lambda s: registrar(
                s, "seguridad.acceso_fallido", f"Intento de acceso fallido para «{nombre}»", detalle={"ip": ip}))
            await asyncio.sleep(RETRASO_FALLO_S)  # frena la fuerza bruta
            return pagina_entrada(request, siguiente=siguiente, estado=401,
                                  error="Usuario o contraseña incorrectos.")

        limitador.exito(claves_limite)

        def abrir(s):
            token = servicio.crear_sesion(s, usuario.id, config.sesion_dias)
            registrar(s, "seguridad.acceso", f"«{usuario.nombre}» inició sesión", detalle={"ip": ip})
            return token

        token = await run_in_threadpool(_con_sesion, sesiones, abrir)
        respuesta = RedirectResponse(siguiente, status_code=303)
        respuesta.set_cookie(COOKIE, token, max_age=int(config.sesion_dias * 86400), httponly=True,
                             samesite="lax", secure=config.cookie_segura, path="/")
        return respuesta

    @app.post("/salir")
    async def salir(request: Request):
        token = request.cookies.get(COOKIE)
        if token:
            await run_in_threadpool(_con_sesion, sesiones, lambda s: servicio.cerrar_sesion(s, token))
        respuesta = RedirectResponse("/entrar", status_code=303)
        respuesta.delete_cookie(COOKIE, path="/")
        return respuesta
