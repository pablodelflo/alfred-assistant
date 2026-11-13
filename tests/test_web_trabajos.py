from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ayudas import cliente_web, iniciar_sesion
from sqlalchemy import create_engine

import alfred.nucleo.minijobs.registro as reg
from alfred.nucleo.config.lectura import Config
from alfred.nucleo.datos.base import Base, crear_sesiones
from alfred.nucleo.datos.modelos import Trabajo
from alfred.nucleo.trabajos.estados import Estado
from alfred.nucleo.trabajos.servicio import cambiar_estado, crear_trabajo
from alfred.nucleo.web.app import crear_app

PRUEBA = Path(__file__).parent / "minijobs_prueba"


@pytest.fixture
def web(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "_carpetas_base", lambda: [PRUEBA])
    motor = create_engine(f"sqlite:///{tmp_path / 'bd.sqlite'}")
    Base.metadata.create_all(motor)
    sesiones = crear_sesiones(motor)
    config = Config(host="x", port=1, url_bd="", zona_temporal=tmp_path / "zona")
    app = crear_app(sesiones=sesiones, config=config)
    cliente = cliente_web(app)
    iniciar_sesion(cliente, sesiones)
    return cliente, sesiones


def nuevo(sesiones, destino=None, **extra):
    with sesiones() as s:
        t = crear_trabajo(s, "espera_y_cuenta", {"pasos": 3})
        for estado in ([Estado.EN_CURSO] if destino else []) + ([destino] if destino and destino is not Estado.EN_CURSO else []):
            cambiar_estado(s, t, estado, **extra)
        s.commit()
        return t.id


def estado(sesiones, tid):
    with sesiones() as s:
        return s.get(Trabajo, tid).estado


def test_lista_vacia(web):
    cliente, _ = web
    r = cliente.get("/trabajos")
    assert r.status_code == 200 and "Todavía no hay trabajos" in r.text


def test_lista_muestra_trabajos_con_nombre_y_estado(web):
    cliente, sesiones = web
    tid = nuevo(sesiones)
    r = cliente.get("/trabajos")
    assert str(tid)[:8] in r.text and "Espera y cuenta (prueba)" in r.text and "Pendiente" in r.text


def test_se_refresca_sola_solo_con_trabajos_activos(web):
    cliente, sesiones = web
    nuevo(sesiones, Estado.TERMINADO)
    assert 'http-equiv="refresh"' not in cliente.get("/trabajos").text
    nuevo(sesiones)  # pendiente
    assert 'http-equiv="refresh"' in cliente.get("/trabajos").text


def test_detalle_con_error_y_detalle_tecnico(web):
    cliente, sesiones = web
    tid = nuevo(sesiones, Estado.FALLIDO, error_usuario="Fichero dañado", error_tecnico="Traceback X")
    r = cliente.get(f"/trabajos/{tid}")
    assert r.status_code == 200 and "Fichero dañado" in r.text and "Traceback X" in r.text
    assert "Fallido" in r.text and "disponibles hasta" in r.text


def test_detalle_inexistente_da_404(web):
    cliente, _ = web
    assert cliente.get("/trabajos/00000000-0000-0000-0000-000000000000").status_code == 404


def test_cancelar_pendiente(web):
    cliente, sesiones = web
    tid = nuevo(sesiones)
    r = cliente.post(f"/trabajos/{tid}/cancelar", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/trabajos/{tid}"
    assert estado(sesiones, tid) == "cancelado"


def test_cancelar_en_curso_pasa_a_cancelandose(web):
    cliente, sesiones = web
    tid = nuevo(sesiones, Estado.EN_CURSO)
    cliente.post(f"/trabajos/{tid}/cancelar")
    assert estado(sesiones, tid) == "cancelandose"


def test_cancelar_un_trabajo_terminado_no_hace_nada(web):
    cliente, sesiones = web
    tid = nuevo(sesiones, Estado.TERMINADO)
    r = cliente.post(f"/trabajos/{tid}/cancelar", follow_redirects=False)
    assert r.status_code == 303 and estado(sesiones, tid) == "terminado"


def test_reintentar_interrumpido(web):
    cliente, sesiones = web
    tid = nuevo(sesiones, Estado.INTERRUMPIDO)
    assert "Reintentar" in cliente.get(f"/trabajos/{tid}").text
    cliente.post(f"/trabajos/{tid}/reintentar")
    assert estado(sesiones, tid) == "pendiente"


def test_reintentar_un_trabajo_que_no_esta_interrumpido_no_hace_nada(web):
    cliente, sesiones = web
    tid = nuevo(sesiones, Estado.FALLIDO)
    cliente.post(f"/trabajos/{tid}/reintentar")
    assert estado(sesiones, tid) == "fallido"


def test_sin_sesiones_no_hay_pantalla_de_trabajos():
    assert TestClient(crear_app()).get("/trabajos").status_code == 404
