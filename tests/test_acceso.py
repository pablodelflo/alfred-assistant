import time
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from ayudas import CLAVE, cliente_web, iniciar_sesion
from alfred.nucleo.config.lectura import Config, ErrorConfig, cargar
from alfred.nucleo.datos.base import Base, crear_sesiones
from alfred.nucleo.datos.modelos import Actividad, Sesion, ahora
from alfred.nucleo.usuarios import claves, servicio
from alfred.nucleo.usuarios.limitador import LimitadorIntentos
from alfred.nucleo.web import acceso
from alfred.nucleo.web.app import crear_app
from alfred.nucleo.zona_temporal.limpieza import limpiar


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    monkeypatch.setattr(acceso, "RETRASO_FALLO_S", 0)
    motor = create_engine(f"sqlite:///{tmp_path / 'bd.sqlite'}")
    Base.metadata.create_all(motor)
    sesiones = crear_sesiones(motor)
    config = Config(host="x", port=1, url_bd="", zona_temporal=tmp_path / "zona")
    app = crear_app(sesiones=sesiones, config=config)
    return cliente_web(app), sesiones, config, app


def con_usuario(sesiones):
    with sesiones() as s:
        servicio.crear_usuario(s, "admin", CLAVE)
        s.commit()


def tipos(sesiones):
    with sesiones() as s:
        return s.scalars(select(Actividad.tipo)).all()


# ---------- protección de las páginas ----------
def test_sin_sesion_se_redirige_a_entrar_recordando_la_pagina(entorno):
    cliente, *_ = entorno
    r = cliente.get("/trabajos?x=1", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/entrar?siguiente=%2Ftrabajos%3Fx%3D1"
    for ruta in ("/", "/catalogo/conversor_medios", "/acerca-de"):
        assert cliente.get(ruta, follow_redirects=False).status_code == 303


def test_los_post_sin_sesion_tambien_se_rechazan(entorno):
    cliente, *_ = entorno
    r = cliente.post("/trabajos/00000000-0000-0000-0000-000000000000/cancelar", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/entrar"
    assert cliente.post("/catalogo/conversor_medios/lanzar", data={}, follow_redirects=False).status_code == 303


def test_lo_publico_sigue_accesible(entorno):
    cliente, *_ = entorno
    assert cliente.get("/estaticos/estilo.css").status_code == 200
    assert cliente.get("/estaticos/favicon.svg").status_code == 200
    assert cliente.get("/favicon.ico", follow_redirects=False).status_code == 307
    assert cliente.get("/entrar").status_code == 200


def test_la_pantalla_de_entrada_avisa_si_no_hay_administrador(entorno):
    cliente, sesiones, *_ = entorno
    assert "python -m alfred.nucleo.usuarios crear" in cliente.get("/entrar").text
    con_usuario(sesiones)
    assert "usuarios crear" not in cliente.get("/entrar").text


def test_la_pantalla_de_entrada_mantiene_el_aviso_de_autoria(entorno):
    cliente, *_ = entorno
    assert "GPL" in cliente.get("/acerca-de", follow_redirects=True).text or "Copyright" in cliente.get("/entrar").text


# ---------- entrada y salida ----------
def test_login_correcto_crea_sesion_con_cookie_segura_y_redirige(entorno):
    cliente, sesiones, *_ = entorno
    con_usuario(sesiones)
    r = cliente.post("/entrar", data={"usuario": "ADMIN", "clave": CLAVE, "siguiente": "/trabajos"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/trabajos"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "secure" not in cookie
    assert cliente.get("/trabajos").status_code == 200
    assert "seguridad.acceso" in tipos(sesiones)


def test_cookie_secure_si_se_configura(entorno):
    cliente, sesiones, config, _ = entorno
    object.__setattr__(config, "cookie_segura", True)
    con_usuario(sesiones)
    r = cliente.post("/entrar", data={"usuario": "admin", "clave": CLAVE}, follow_redirects=False)
    assert "secure" in r.headers["set-cookie"].lower()


def test_el_token_no_se_guarda_en_claro(entorno):
    cliente, sesiones, *_ = entorno
    iniciar_sesion(cliente, sesiones)
    token = cliente.cookies.get("alfred_sesion")
    with sesiones() as s:
        [fila] = s.scalars(select(Sesion)).all()
    assert fila.token_hash != token and len(fila.token_hash) == 64


@pytest.mark.parametrize("siguiente, esperado", [
    ("/trabajos", "/trabajos"), ("//evil.com", "/"), ("https://evil.com/x", "/"),
    ("/\\evil.com", "/"), ("", "/"), ("trabajos", "/")])
def test_la_redireccion_tras_entrar_solo_va_a_rutas_internas(entorno, siguiente, esperado):
    cliente, sesiones, *_ = entorno
    con_usuario(sesiones)
    r = cliente.post("/entrar", data={"usuario": "admin", "clave": CLAVE, "siguiente": siguiente}, follow_redirects=False)
    assert r.headers["location"] == esperado


def test_error_de_credenciales_es_igual_para_usuario_inexistente_y_clave_mala(entorno):
    cliente, sesiones, *_ = entorno
    con_usuario(sesiones)
    a = cliente.post("/entrar", data={"usuario": "admin", "clave": "mala-mala-mala"})
    b = cliente.post("/entrar", data={"usuario": "nadie", "clave": "mala-mala-mala"})
    assert a.status_code == b.status_code == 401
    assert "Usuario o contraseña incorrectos" in a.text and "Usuario o contraseña incorrectos" in b.text
    assert tipos(sesiones).count("seguridad.acceso_fallido") == 2
    assert "alfred_sesion" not in cliente.cookies


def test_bloqueo_tras_demasiados_intentos_incluso_con_la_clave_correcta(entorno):
    cliente, sesiones, config, _ = entorno
    object.__setattr__(config, "intentos_max", 3)  # se lee en cada intento
    con_usuario(sesiones)
    for _ in range(3):
        assert cliente.post("/entrar", data={"usuario": "admin", "clave": "mala-mala-mala"}).status_code == 401
    r = cliente.post("/entrar", data={"usuario": "admin", "clave": CLAVE})
    assert r.status_code == 429 and "Demasiados intentos" in r.text
    assert cliente.get("/trabajos", follow_redirects=False).status_code == 303  # no entró


def test_cerrar_sesion_invalida_la_cookie(entorno):
    cliente, sesiones, config, app = entorno
    iniciar_sesion(cliente, sesiones)
    token = cliente.cookies.get("alfred_sesion")
    r = cliente.post("/salir", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/entrar"
    otro = cliente_web(app)
    otro.cookies.set("alfred_sesion", token)
    assert otro.get("/trabajos", follow_redirects=False).status_code == 303


def test_sesion_caducada(entorno):
    cliente, sesiones, *_ = entorno
    iniciar_sesion(cliente, sesiones)
    with sesiones() as s:
        for fila in s.scalars(select(Sesion)):
            fila.expira_en = ahora() - timedelta(minutes=1)
        s.commit()
    r = cliente.get("/trabajos", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/entrar")
    with sesiones() as s:
        assert s.scalars(select(Sesion)).all() == []  # se borra al detectarla


def test_la_limpieza_borra_sesiones_caducadas(entorno):
    cliente, sesiones, config, _ = entorno
    iniciar_sesion(cliente, sesiones)
    with sesiones() as s:
        s.add(Sesion(token_hash="x" * 64, usuario_id=1, expira_en=ahora() - timedelta(days=1)))
        s.commit()
    limpiar(sesiones, config.zona_temporal, 6)
    with sesiones() as s:
        assert len(s.scalars(select(Sesion)).all()) == 1


def test_cambiar_la_clave_cierra_las_sesiones(entorno):
    cliente, sesiones, *_ = entorno
    iniciar_sesion(cliente, sesiones)
    with sesiones() as s:
        assert servicio.cambiar_clave(s, "admin", "otra-clave-larga-456") == 1
        s.commit()
    assert cliente.get("/trabajos", follow_redirects=False).status_code == 303
    r = cliente.post("/entrar", data={"usuario": "admin", "clave": "otra-clave-larga-456"}, follow_redirects=False)
    assert r.status_code == 303


# ---------- protección contra peticiones falsas ----------
def test_post_desde_otro_origen_se_rechaza(entorno):
    cliente, sesiones, config, app = entorno
    iniciar_sesion(cliente, sesiones)
    r = cliente.post("/salir", headers={"Origin": "http://evil.example"}, follow_redirects=False)
    assert r.status_code == 403
    assert cliente.get("/trabajos").status_code == 200  # la sesión sigue viva


def test_post_sin_origen_ni_referer_se_rechaza(entorno):
    _, sesiones, config, app = entorno
    navegador = TestClient(app, base_url="http://testserver")  # sin cabeceras
    assert navegador.post("/entrar", data={"usuario": "a", "clave": "b"}).status_code == 403
    assert navegador.post("/entrar", data={"usuario": "a", "clave": "b"},
                          headers={"Origin": "null"}).status_code == 403


def test_el_referer_del_mismo_sitio_vale_si_no_hay_origin(entorno):
    _, sesiones, config, app = entorno
    navegador = TestClient(app, base_url="http://testserver")
    r = navegador.post("/entrar", data={"usuario": "a", "clave": "b"},
                       headers={"Referer": "http://testserver/entrar"})
    assert r.status_code == 401  # llegó a comprobar las credenciales


def test_origenes_permitidos_extra_para_proxys(entorno):
    _, sesiones, config, app = entorno
    object.__setattr__(config, "origenes_permitidos", ("alfred.casa",))
    navegador = TestClient(app, base_url="http://testserver")
    assert navegador.post("/entrar", data={"usuario": "a", "clave": "b"},
                          headers={"Origin": "https://alfred.casa"}).status_code == 401


# ---------- contraseñas ----------
def test_formato_del_hash_y_verificacion(monkeypatch):
    monkeypatch.setattr(claves, "N_LOG2", claves.N_LOG2_DEFECTO)
    a, b = claves.hashear("secreto-secreto"), claves.hashear("secreto-secreto")
    assert a != b and a.startswith("scrypt$15$8$1$")  # sal distinta cada vez; coste real
    assert claves.verificar("secreto-secreto", a) and not claves.verificar("otro-secreto", a)


@pytest.mark.parametrize("basura", ["", "texto", "scrypt$1$2", "md5$15$8$1$aa$bb", "scrypt$x$8$1$aa$bb"])
def test_hash_corrupto_no_verifica_ni_lanza(basura):
    assert claves.verificar("lo-que-sea", basura) is False


def test_reglas_de_contrasena_y_unico_administrador(entorno):
    _, sesiones, *_ = entorno
    with sesiones() as s:
        for mala in ("corta", "admin"):
            with pytest.raises(servicio.ErrorUsuario):
                servicio.crear_usuario(s, "admin", mala)
        servicio.crear_usuario(s, "admin", CLAVE)
        with pytest.raises(servicio.ErrorUsuario, match="Ya existe"):
            servicio.crear_usuario(s, "otro", CLAVE)
        with pytest.raises(servicio.ErrorUsuario, match="No existe"):
            servicio.cambiar_clave(s, "nadie", CLAVE)


# ---------- limitador ----------
def test_limitador_bloquea_y_se_desbloquea_con_el_tiempo():
    ahora_ = [1000.0]
    lim = LimitadorIntentos(reloj=lambda: ahora_[0])
    claves_ = ["ip:1", "usuario:a"]
    for _ in range(3):
        assert lim.segundos_de_bloqueo(claves_, 3, 600) == 0
        lim.fallo(claves_)
    assert 0 < lim.segundos_de_bloqueo(claves_, 3, 600) <= 601
    assert lim.segundos_de_bloqueo(["ip:2", "usuario:b"], 3, 600) == 0  # otros no se ven afectados
    ahora_[0] += 601
    assert lim.segundos_de_bloqueo(claves_, 3, 600) == 0


def test_limitador_exito_reinicia_la_cuenta():
    lim = LimitadorIntentos()
    lim.fallo(["a"]); lim.fallo(["a"])
    lim.exito(["a"])
    lim.fallo(["a"])
    assert lim.segundos_de_bloqueo(["a"], 3, 60) == 0


# ---------- configuración y terminal ----------
def test_configuracion_de_seguridad(tmp_path):
    base = '[base_datos]\nurl = "postgresql://a:b@localhost/c"\n[servidor]\n'
    ruta = tmp_path / "s.toml"
    ruta.write_text(base, encoding="utf-8")
    c = cargar(ruta)
    assert (c.sesion_dias, c.cookie_segura, c.intentos_max, c.bloqueo_minutos, c.origenes_permitidos) == (30, False, 5, 15, ())
    ruta.write_text(base + '[seguridad]\nsesion_dias = 7\ncookie_segura = true\norigenes_permitidos = ["a.casa"]\n', encoding="utf-8")
    c = cargar(ruta)
    assert (c.sesion_dias, c.cookie_segura, c.origenes_permitidos) == (7, True, ("a.casa",))
    ruta.write_text(base + "[seguridad]\nintentos_max = 0\n", encoding="utf-8")
    with pytest.raises(ErrorConfig):
        cargar(ruta)


def test_comando_de_terminal(tmp_path, monkeypatch, capsys):
    import getpass
    from alfred.nucleo.usuarios.__main__ import main
    bd = tmp_path / "bd.sqlite"
    motor = create_engine(f"sqlite:///{bd}")
    Base.metadata.create_all(motor)
    (tmp_path / "s.toml").write_text(f'[servidor]\n[base_datos]\nurl = "sqlite:///{bd}"\n', encoding="utf-8")
    monkeypatch.setenv("ALFRED_CONFIG", str(tmp_path / "s.toml"))
    monkeypatch.setattr(getpass, "getpass", lambda _: CLAVE)
    assert main(["crear"]) == 0 and "creado" in capsys.readouterr().out
    assert main(["crear", "otro"]) == 1 and "Ya existe" in capsys.readouterr().out
    assert main(["listar"]) == 0 and "admin" in capsys.readouterr().out
    assert main(["cambiar-clave"]) == 0
    assert main(["cerrar-sesiones"]) == 0
    monkeypatch.setattr(getpass, "getpass", lambda _: "corta")
    assert main(["cambiar-clave"]) == 1
    assert main([]) == 2
