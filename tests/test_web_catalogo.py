"""Formulario generado, subida por la web, conversión real y descarga, de punta a punta."""
import io
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, select

pytest.importorskip("pillow_heif")
import pillow_heif  # noqa: E402

from alfred.nucleo.config.lectura import Config  # noqa: E402
from alfred.nucleo.datos.base import Base, crear_sesiones  # noqa: E402
from alfred.nucleo.datos.modelos import Trabajo  # noqa: E402
from alfred.nucleo.trabajos.lanzador import Lanzador  # noqa: E402
from alfred.nucleo.web.app import crear_app  # noqa: E402
from alfred.nucleo.zona_temporal.rutas import carpeta_trabajo  # noqa: E402

pillow_heif.register_heif_opener()


def heic_bytes(tam=(64, 48), color=(10, 120, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", tam, color).save(buf, format="HEIF", quality=80)
    return buf.getvalue()


@pytest.fixture
def entorno(tmp_path):
    motor = create_engine(f"sqlite:///{tmp_path / 'bd.sqlite'}")
    Base.metadata.create_all(motor)
    sesiones = crear_sesiones(motor)
    config = Config(host="x", port=1, url_bd="", zona_temporal=tmp_path / "zona")
    return TestClient(crear_app(sesiones=sesiones, config=config)), sesiones, config, tmp_path


def datos(**extra):
    base = {"conversion": "heic_a_jpg", "calidad": "85", "conservar_metadatos": "on"}
    base.update(extra)
    return base


def trabajos(sesiones):
    with sesiones() as s:
        return s.scalars(select(Trabajo)).all()


def test_el_formulario_se_genera_desde_el_manifiesto(entorno):
    cliente, *_ = entorno
    html = cliente.get("/catalogo/conversor_medios").text
    assert "Si el nombre ya existe" not in html
    for esperado in ("HEIC → JPG", "Calidad del JPG", 'name="ficheros"', "webkitdirectory", 'accept=".heic,.heif"',
                     "Quitar la ubicación GPS", "Máximo 1000 ficheros", "subida.js"):
        assert esperado in html, esperado


def test_minijob_inexistente_o_no_disponible(entorno, tmp_path, monkeypatch):
    cliente, sesiones, config, _ = entorno
    assert cliente.get("/catalogo/no_existe").status_code == 404
    import alfred.nucleo.minijobs.registro as reg
    carpeta = tmp_path / "mj" / "roto"
    carpeta.mkdir(parents=True)
    (carpeta / "ejecutar.py").write_text("")
    (carpeta / "manifiesto.toml").write_text('id="roto"\nnombre="Roto"\ndescripcion="d"\ncategoria="c"\n'
                                             'version="1"\npeso="ligero"\ntiempo_maximo=60\n'
                                             'dependencias=["modulo_que_no_existe_xyz"]\n')
    monkeypatch.setattr(reg, "_carpetas_base", lambda: [carpeta.parent])
    assert "No disponible" in cliente.get("/").text
    assert cliente.post("/catalogo/roto/lanzar", data={}).status_code == 400


def test_subir_sin_ficheros_da_error_y_no_crea_trabajo(entorno):
    cliente, sesiones, *_ = entorno
    r = cliente.post("/catalogo/conversor_medios/lanzar", data=datos())
    assert r.status_code == 422 and "Elige al menos un fichero" in r.text and not trabajos(sesiones)


def test_valores_invalidos_se_reciben_con_mensaje_y_se_conservan(entorno):
    cliente, sesiones, *_ = entorno
    r = cliente.post("/catalogo/conversor_medios/lanzar", data=datos(calidad="500"),
                     files=[("ficheros", ("a.heic", heic_bytes()))])
    assert r.status_code == 422 and "Debe estar entre 1 y 100" in r.text and 'value="500"' in r.text
    assert not trabajos(sesiones)


def test_subida_crea_trabajo_con_ficheros_y_opciones(entorno):
    cliente, sesiones, config, _ = entorno
    r = cliente.post("/catalogo/conversor_medios/lanzar", data=datos(quitar_gps="on"), follow_redirects=False,
                     files=[("ficheros", ("a.heic", heic_bytes())),
                            ("ficheros", ("viaje/b.heic", heic_bytes())),
                            ("ficheros", ("notas.txt", b"hola"))])
    assert r.status_code == 303
    [t] = trabajos(sesiones)
    assert r.headers["location"] == f"/trabajos/{t.id}" and t.estado == "pendiente"
    assert t.entradas["calidad"] == 85 and t.entradas["quitar_gps"] is True
    assert t.entradas["conservar_metadatos"] is True and t.entradas["ficheros"] == ["a.heic", "viaje/b.heic"]
    assert t.entradas["ficheros_ignorados"] == 1
    assert (carpeta_trabajo(config.zona_temporal, t.id) / "entrada" / "viaje" / "b.heic").is_file()


def test_solo_ficheros_de_tipo_no_admitido_da_error(entorno):
    cliente, sesiones, config, _ = entorno
    r = cliente.post("/catalogo/conversor_medios/lanzar", data=datos(), files=[("ficheros", ("x.txt", b"hola"))])
    assert r.status_code == 413 and "tipo admitido" in r.text
    assert not trabajos(sesiones) and not list(config.zona_temporal.glob("*"))


@pytest.mark.parametrize("limite, mensaje", [
    ({"max_fichero_mb": 0.00001}, "por fichero"),
    ({"max_ficheros": 1}, "ficheros"),
    ({"max_lote_mb": 0.00001}, "por lote")])
def test_los_limites_se_leen_de_la_configuracion_al_momento(entorno, limite, mensaje):
    cliente, sesiones, config, _ = entorno
    for clave, valor in limite.items():
        object.__setattr__(config, clave, valor)  # como haría una pantalla de ajustes futura
    r = cliente.post("/catalogo/conversor_medios/lanzar", data=datos(),
                     files=[("ficheros", ("a.heic", heic_bytes())), ("ficheros", ("b.heic", heic_bytes()))])
    assert r.status_code in (400, 413) and mensaje in r.text
    assert not trabajos(sesiones) and not list(config.zona_temporal.glob("*"))  # sin restos


def test_de_punta_a_punta_subir_convertir_y_descargar(entorno):
    cliente, sesiones, config, tmp_path = entorno
    r = cliente.post("/catalogo/conversor_medios/lanzar", data=datos(calidad="90"), follow_redirects=False,
                     files=[("ficheros", ("a.heic", heic_bytes((64, 48)))),
                            ("ficheros", ("viaje/b.heic", heic_bytes((40, 30)))),
                            ("ficheros", ("roto.heic", b"no soy una imagen"))])
    assert r.status_code == 303
    tid = r.headers["location"].split("/")[-1]

    lanzador = Lanzador(sesiones, config.zona_temporal.resolve(), gracia_cancelacion_s=1)
    fin = time.monotonic() + 60
    while time.monotonic() < fin:
        lanzador.tick()
        with sesiones() as s:
            t = s.scalars(select(Trabajo)).one()
        if t.estado not in ("pendiente", "en_curso"):
            break
        time.sleep(0.1)
    assert t.estado == "terminado_con_avisos", (t.estado, t.error_usuario, t.error_tecnico)
    assert t.informe["resumen"] == "2 convertidos, 0 omitidos, 1 fallidos"

    pagina = cliente.get(f"/trabajos/{tid}").text
    assert "Descargar todo (ZIP)" in pagina and "viaje/b.jpg" in pagina and "roto.heic" in pagina

    uno = cliente.get(f"/trabajos/{tid}/ficheros/a.jpg")
    assert uno.status_code == 200 and "attachment" in uno.headers["content-disposition"]
    assert Image.open(io.BytesIO(uno.content)).size == (64, 48)

    zip_ = cliente.get(f"/trabajos/{tid}/resultado.zip")
    assert zip_.status_code == 200 and zip_.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(zip_.content)) as z:
        assert sorted(z.namelist()) == ["a.jpg", "viaje/b.jpg"]

    assert cliente.get(f"/trabajos/{tid}/ficheros/..%2f..%2fbd.sqlite").status_code == 404
    assert cliente.get(f"/trabajos/{tid}/ficheros/entrada/a.heic").status_code == 404  # solo la salida


def test_sin_resultados_disponibles_no_hay_descarga(entorno):
    cliente, sesiones, config, _ = entorno
    cliente.post("/catalogo/conversor_medios/lanzar", data=datos(), files=[("ficheros", ("a.heic", heic_bytes()))])
    [t] = trabajos(sesiones)  # sigue pendiente: aún no hay resultados
    assert cliente.get(f"/trabajos/{t.id}/resultado.zip").status_code == 404
    assert cliente.get(f"/trabajos/{t.id}/ficheros/a.jpg").status_code == 404
