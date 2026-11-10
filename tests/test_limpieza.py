import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select

import alfred.nucleo.minijobs.registro as reg
from alfred.nucleo.datos.base import Base, crear_sesiones
from alfred.nucleo.datos.modelos import Actividad, Trabajo
from alfred.nucleo.trabajos.estados import Estado
from alfred.nucleo.trabajos.servicio import TransicionInvalida, cambiar_estado, crear_trabajo, reintentar
from alfred.nucleo.zona_temporal.limpieza import Limpiador, caduca_en, limpiar
from alfred.nucleo.zona_temporal.rutas import carpeta_trabajo

PRUEBA = Path(__file__).parent / "minijobs_prueba"


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "_carpetas_base", lambda: [PRUEBA])
    motor = create_engine(f"sqlite:///{tmp_path / 'bd.sqlite'}")
    Base.metadata.create_all(motor)
    zona = tmp_path / "zona"
    zona.mkdir()
    return crear_sesiones(motor), zona


def trabajo_con_ficheros(entorno, destino: Estado, minijob="espera_y_cuenta") -> uuid.UUID:
    sesiones, zona = entorno
    with sesiones() as s:
        t = crear_trabajo(s, minijob, {})
        if destino is Estado.INTERRUMPIDO or destino in (Estado.TERMINADO, Estado.FALLIDO, Estado.TERMINADO_CON_AVISOS):
            cambiar_estado(s, t, Estado.EN_CURSO)
            cambiar_estado(s, t, destino)
        s.commit()
        carpeta = carpeta_trabajo(zona, t.id)
        (carpeta / "salida").mkdir(parents=True)
        (carpeta / "salida" / "x.txt").write_text("datos")
        return t.id


def trabajo(sesiones, tid) -> Trabajo:
    with sesiones() as s:
        return s.get(Trabajo, tid)


def en(horas):
    return datetime.now(timezone.utc) + timedelta(hours=horas)


def test_no_borra_antes_de_caducar_y_si_despues(entorno):
    sesiones, zona = entorno
    tid = trabajo_con_ficheros(entorno, Estado.TERMINADO)
    assert limpiar(sesiones, zona, 6, ahora=en(5.9)) == 0
    assert carpeta_trabajo(zona, tid).exists()
    assert limpiar(sesiones, zona, 6, ahora=en(6.1)) == 1
    assert not carpeta_trabajo(zona, tid).exists()
    t = trabajo(sesiones, tid)  # la fila del historial se conserva
    assert t.estado == "terminado" and t.ficheros_eliminados_en is not None
    with sesiones() as s:
        assert "zona_temporal.limpieza" in s.scalars(select(Actividad.tipo)).all()
    assert limpiar(sesiones, zona, 6, ahora=en(100)) == 0  # no se repite


@pytest.mark.parametrize("estado", [Estado.TERMINADO, Estado.TERMINADO_CON_AVISOS, Estado.FALLIDO, Estado.INTERRUMPIDO])
def test_caducan_los_estados_con_ficheros(entorno, estado):
    sesiones, zona = entorno
    tid = trabajo_con_ficheros(entorno, estado)
    limpiar(sesiones, zona, 1, ahora=en(2))
    assert not carpeta_trabajo(zona, tid).exists()


def test_no_toca_trabajos_vivos(entorno):
    sesiones, zona = entorno
    pendiente = trabajo_con_ficheros(entorno, Estado.PENDIENTE)
    limpiar(sesiones, zona, 1, ahora=en(1000))
    assert carpeta_trabajo(zona, pendiente).exists()


def test_cero_no_caduca_nunca(entorno):
    sesiones, zona = entorno
    tid = trabajo_con_ficheros(entorno, Estado.TERMINADO)
    assert limpiar(sesiones, zona, 0, ahora=en(100000)) == 0
    assert carpeta_trabajo(zona, tid).exists() and caduca_en(trabajo(sesiones, tid), 0) is None


def test_el_minijob_puede_fijar_su_propia_conservacion(entorno, tmp_path, monkeypatch):
    sesiones, zona = entorno
    otro = tmp_path / "minijobs" / "largo"
    otro.mkdir(parents=True)
    (otro / "ejecutar.py").write_text("")
    (otro / "manifiesto.toml").write_text('id="largo"\nnombre="L"\ndescripcion="d"\ncategoria="c"\n'
                                          'version="1"\npeso="ligero"\ntiempo_maximo=60\nconservacion_horas=48\n')
    monkeypatch.setattr(reg, "_carpetas_base", lambda: [otro.parent])
    tid = trabajo_con_ficheros(entorno, Estado.TERMINADO, "largo")
    limpiar(sesiones, zona, 6, ahora=en(10))   # pasó el valor por defecto, no el suyo
    assert carpeta_trabajo(zona, tid).exists()
    limpiar(sesiones, zona, 6, ahora=en(49))
    assert not carpeta_trabajo(zona, tid).exists()


def test_reintentar_se_bloquea_si_ya_se_limpiaron_los_ficheros(entorno):
    sesiones, zona = entorno
    tid = trabajo_con_ficheros(entorno, Estado.INTERRUMPIDO)
    assert trabajo(sesiones, tid).terminado_en is not None  # interrumpido también marca su fin
    limpiar(sesiones, zona, 1, ahora=en(2))
    with sesiones() as s, pytest.raises(TransicionInvalida, match="ya se eliminaron"):
        reintentar(s, s.get(Trabajo, tid))


def test_carpetas_huerfanas(entorno):
    sesiones, zona = entorno
    vieja_sin_trabajo = zona / str(uuid.uuid4())
    reciente_sin_trabajo = zona / str(uuid.uuid4())
    ajena = zona / "no_es_de_alfred"
    for c in (vieja_sin_trabajo, reciente_sin_trabajo, ajena):
        c.mkdir()
    hace_dos_horas = time.time() - 7200
    for c in (vieja_sin_trabajo, ajena):
        os.utime(c, (hace_dos_horas, hace_dos_horas))
    activo = trabajo_con_ficheros(entorno, Estado.PENDIENTE)
    os.utime(carpeta_trabajo(zona, activo), (hace_dos_horas, hace_dos_horas))

    assert limpiar(sesiones, zona, 6) == 1
    assert not vieja_sin_trabajo.exists()
    assert reciente_sin_trabajo.exists()   # puede ser una subida aún sin trabajo
    assert ajena.exists()                  # no es una carpeta de Alfred
    assert carpeta_trabajo(zona, activo).exists()


def test_el_limpiador_limpia_al_arrancar_y_se_para(entorno):
    sesiones, zona = entorno
    tid = trabajo_con_ficheros(entorno, Estado.TERMINADO)
    with sesiones() as s:  # fingimos que terminó hace una semana
        s.get(Trabajo, tid).terminado_en = en(-24 * 7)
        s.commit()
    limpiador = Limpiador(sesiones, zona, 6, cada_minutos=60)
    limpiador.start()
    fin = time.monotonic() + 10
    while time.monotonic() < fin and carpeta_trabajo(zona, tid).exists():
        time.sleep(0.05)
    limpiador.stop()
    assert not carpeta_trabajo(zona, tid).exists()
