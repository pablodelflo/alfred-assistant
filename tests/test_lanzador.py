"""Lanzador con procesos reales y base de datos SQLite en un fichero temporal."""
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select

import alfred.nucleo.minijobs.registro as reg
from alfred.nucleo.datos.base import Base, crear_sesiones
from alfred.nucleo.datos.modelos import Actividad, Trabajo
from alfred.nucleo.trabajos.estados import Estado
from alfred.nucleo.trabajos.lanzador import Lanzador
from alfred.nucleo.trabajos.recuperacion import es_proceso_de_trabajo, recuperar
from alfred.nucleo.trabajos.servicio import (TransicionInvalida, crear_trabajo, reintentar,
                                             solicitar_cancelacion)
from alfred.nucleo.zona_temporal.rutas import carpeta_trabajo

PRUEBA = Path(__file__).parent / "minijobs_prueba"


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "_carpetas_base", lambda: [PRUEBA])
    motor = create_engine(f"sqlite:///{tmp_path / 'bd.sqlite'}")
    Base.metadata.create_all(motor)
    sesiones = crear_sesiones(motor)
    zona = tmp_path / "zona"
    zona.mkdir()
    return sesiones, zona


def nuevo_lanzador(entorno, **kw):
    sesiones, zona = entorno
    kw.setdefault("gracia_cancelacion_s", 0.5)
    return Lanzador(sesiones, zona, **kw)


def crear(sesiones, entradas, minijob="espera_y_cuenta"):
    with sesiones() as s:
        t = crear_trabajo(s, minijob, entradas)
        s.commit()
        return t.id


def estado(sesiones, tid) -> Trabajo:
    with sesiones() as s:
        return s.get(Trabajo, tid)


def esperar(lanzador, sesiones, tid, condicion, limite=30):
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        lanzador.tick()
        t = estado(sesiones, tid)
        if condicion(t):
            return t
        time.sleep(0.05)
    raise AssertionError(f"no se cumplió la condición; estado={estado(sesiones, tid).estado}")


def final(t):
    return t.estado in {e.value for e in (Estado.TERMINADO, Estado.TERMINADO_CON_AVISOS,
                                          Estado.FALLIDO, Estado.CANCELADO, Estado.INTERRUMPIDO)}


def test_flujo_normal(entorno):
    sesiones, zona = entorno
    l = nuevo_lanzador(entorno)
    tid = crear(sesiones, {"pasos": 3, "segundos_por_paso": 0.1})
    t = esperar(l, sesiones, tid, final)
    assert t.estado == "terminado" and t.progreso == 100 and t.pid is None
    assert t.informe["resumen"] == "3 pasos correctos, 0 fallidos"
    assert (carpeta_trabajo(zona, tid) / "salida" / "resultado.txt").is_file()
    with sesiones() as s:
        tipos = s.scalars(select(Actividad.tipo)).all()
    assert "trabajo.lanzado" in tipos and tipos.count("trabajo.estado") == 2


def test_fallos_parciales_terminan_con_avisos(entorno):
    sesiones, _ = entorno
    l = nuevo_lanzador(entorno)
    tid = crear(sesiones, {"pasos": 3, "segundos_por_paso": 0.05, "fallos_parciales": 1})
    t = esperar(l, sesiones, tid, final)
    assert t.estado == "terminado_con_avisos" and len(t.informe["fallos"]) == 1


def test_error_de_usuario(entorno):
    sesiones, _ = entorno
    l = nuevo_lanzador(entorno)
    tid = crear(sesiones, {"pasos": 5, "segundos_por_paso": 0.05, "fallar": "usuario"})
    t = esperar(l, sesiones, tid, final)
    assert t.estado == "fallido" and t.error_usuario == "Fichero de prueba dañado"
    assert "ErrorUsuario" in t.error_tecnico


def test_error_inesperado_da_mensaje_generico_y_detalle_tecnico(entorno):
    sesiones, _ = entorno
    l = nuevo_lanzador(entorno)
    tid = crear(sesiones, {"pasos": 5, "segundos_por_paso": 0.05, "fallar": "inesperado"})
    t = esperar(l, sesiones, tid, final)
    assert t.estado == "fallido" and "inesperada" in t.error_usuario
    assert "RuntimeError" in t.error_tecnico and "Traceback" in t.error_tecnico


def test_progreso_llega_a_la_base_de_datos(entorno):
    sesiones, _ = entorno
    l = nuevo_lanzador(entorno)
    tid = crear(sesiones, {"pasos": 20, "segundos_por_paso": 0.1})
    t = esperar(l, sesiones, tid, lambda t: 0 < t.progreso < 100)
    assert t.estado == "en_curso" and t.mensaje_progreso.startswith("Paso") and t.pid
    solicitar = sesiones()
    with solicitar as s:
        solicitar_cancelacion(s, s.get(Trabajo, tid), entorno[1]); s.commit()
    esperar(l, sesiones, tid, final)


def test_cancelacion_cooperativa_limpia_la_carpeta(entorno):
    sesiones, zona = entorno
    l = nuevo_lanzador(entorno, gracia_cancelacion_s=10)
    tid = crear(sesiones, {"pasos": 100, "segundos_por_paso": 0.1})
    esperar(l, sesiones, tid, lambda t: t.progreso > 0)
    with sesiones() as s:
        solicitar_cancelacion(s, s.get(Trabajo, tid), zona); s.commit()
    assert estado(sesiones, tid).estado == "cancelandose"
    t0 = time.monotonic()
    t = esperar(l, sesiones, tid, final)
    assert t.estado == "cancelado" and time.monotonic() - t0 < 5  # paró por las buenas, sin esperar la gracia
    assert not carpeta_trabajo(zona, tid).exists()


def test_cancelacion_forzada_si_el_minijob_no_responde(entorno):
    sesiones, zona = entorno
    l = nuevo_lanzador(entorno, gracia_cancelacion_s=0.5)
    tid = crear(sesiones, {"pasos": 200, "segundos_por_paso": 0.1, "ignorar_cancelacion": True})
    t = esperar(l, sesiones, tid, lambda t: t.progreso > 0)
    pid = t.pid
    with sesiones() as s:
        solicitar_cancelacion(s, s.get(Trabajo, tid), zona); s.commit()
    t = esperar(l, sesiones, tid, final)
    assert t.estado == "cancelado" and not Path(f"/proc/{pid}").exists()


def test_cancelar_pendiente_es_inmediato(entorno):
    sesiones, zona = entorno
    tid = crear(sesiones, {})
    with sesiones() as s:
        solicitar_cancelacion(s, s.get(Trabajo, tid), zona); s.commit()
    assert estado(sesiones, tid).estado == "cancelado"
    with sesiones() as s, pytest.raises(TransicionInvalida):
        solicitar_cancelacion(s, s.get(Trabajo, tid), zona)


def test_tiempo_maximo(entorno, tmp_path, monkeypatch):
    sesiones, _ = entorno
    otro = tmp_path / "minijobs"
    destino = otro / "lento"
    shutil.copytree(PRUEBA / "espera_y_cuenta", destino)
    (destino / "manifiesto.toml").write_text(
        (destino / "manifiesto.toml").read_text().replace('"espera_y_cuenta"', '"lento"').replace("= 120", "= 1"))
    monkeypatch.setattr(reg, "_carpetas_base", lambda: [otro])
    l = nuevo_lanzador(entorno, gracia_cancelacion_s=0.5)
    tid = crear(sesiones, {"pasos": 100, "segundos_por_paso": 0.2, "ignorar_cancelacion": True}, "lento")
    t = esperar(l, sesiones, tid, final)
    assert t.estado == "fallido" and "tiempo máximo" in t.error_usuario


def test_concurrencia_limitada_por_peso(entorno):
    sesiones, _ = entorno
    l = nuevo_lanzador(entorno, max_ligeros=1)
    a = crear(sesiones, {"pasos": 6, "segundos_por_paso": 0.1})
    b = crear(sesiones, {"pasos": 2, "segundos_por_paso": 0.05})
    l.tick()
    assert (estado(sesiones, a).estado, estado(sesiones, b).estado) == ("en_curso", "pendiente")
    esperar(l, sesiones, b, final)
    assert estado(sesiones, a).estado == "terminado"  # a acabó antes de que b empezara


def test_minijob_inexistente_falla_con_mensaje(entorno):
    sesiones, _ = entorno
    l = nuevo_lanzador(entorno)
    tid = crear(sesiones, {}, "no_existe")
    t = esperar(l, sesiones, tid, final)
    assert t.estado == "fallido" and "no está instalado" in t.error_usuario


def test_parada_de_alfred_interrumpe_y_permite_reintentar(entorno):
    sesiones, zona = entorno
    l = nuevo_lanzador(entorno, gracia_cancelacion_s=2)
    tid = crear(sesiones, {"pasos": 100, "segundos_por_paso": 0.1})
    t = esperar(l, sesiones, tid, lambda t: t.progreso > 0)
    pid = t.pid
    l.stop()
    t = estado(sesiones, tid)
    assert t.estado == "interrumpido" and t.pid is None and not Path(f"/proc/{pid}").exists()
    with sesiones() as s:
        reintentar(s, s.get(Trabajo, tid)); s.commit()
    assert estado(sesiones, tid).estado == "pendiente"


def test_recuperacion_marca_interrumpidos_y_mata_huerfanos(entorno):
    sesiones, _ = entorno
    # Un «huérfano»: su línea de órdenes contiene la marca de los procesos de trabajo.
    huerfano = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)",
                                 "alfred.nucleo.trabajos.proceso"], start_new_session=True)
    a = crear(sesiones, {})
    b = crear(sesiones, {})
    with sesiones() as s:
        s.get(Trabajo, a).estado, s.get(Trabajo, a).pid = "en_curso", huerfano.pid
        s.get(Trabajo, b).estado, s.get(Trabajo, b).pid = "en_curso", None
        s.commit()
    assert recuperar(sesiones) == 2
    assert huerfano.wait(timeout=5) == -9
    assert estado(sesiones, a).estado == estado(sesiones, b).estado == "interrumpido"
    assert estado(sesiones, a).pid is None


def test_recuperacion_no_mata_procesos_ajenos(entorno):
    sesiones, _ = entorno
    ajeno = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    try:
        assert not es_proceso_de_trabajo(ajeno.pid)
        tid = crear(sesiones, {})
        with sesiones() as s:
            s.get(Trabajo, tid).estado, s.get(Trabajo, tid).pid = "en_curso", ajeno.pid
            s.commit()
        recuperar(sesiones)
        assert ajeno.poll() is None  # sigue vivo
    finally:
        ajeno.kill()
