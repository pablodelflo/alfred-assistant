"""Conversor HEIC → JPG con fotos HEIC reales generadas al vuelo."""
import importlib
from pathlib import Path

import pytest

pytest.importorskip("pillow_heif")
from PIL import Image  # noqa: E402

import pillow_heif  # noqa: E402

from alfred.comun.contrato import Cancelado, Contexto, ErrorUsuario  # noqa: E402

pillow_heif.register_heif_opener()
ejecutar = importlib.import_module("alfred.minijobs.conversor_medios.ejecutar").ejecutar


def heic(ruta: Path, tam=(64, 48), color=(200, 30, 30), exif=None):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    kw = {"exif": exif} if exif is not None else {}
    Image.new("RGB", tam, color).save(ruta, quality=80, **kw)


def exif_con_gps():
    e = Image.Exif()
    e[0x010F] = "MarcaPrueba"
    e[0x8825] = {1: "N", 2: (37.0, 23.0, 25.0), 3: "W", 4: (5.0, 58.0, 0.0)}
    return e


@pytest.fixture
def ctx(tmp_path):
    def crear(entradas=None):
        c = Contexto(entradas=entradas or {}, carpeta_entrada=tmp_path / "entrada",
                     carpeta_temporal=tmp_path / "temporal", carpeta_salida=tmp_path / "salida",
                     _emitir=lambda linea: None)
        for d in (c.carpeta_entrada, c.carpeta_temporal, c.carpeta_salida):
            d.mkdir(exist_ok=True)
        return c
    return crear


BASE = {"conversion": "heic_a_jpg"}


def test_convierte_y_conserva_subcarpetas(ctx):
    c = ctx(BASE)
    heic(c.carpeta_entrada / "a.heic")
    heic(c.carpeta_entrada / "viaje" / "b.HEIC", tam=(40, 30))
    informe = ejecutar(c)
    assert informe.resumen == "2 convertidos, 0 omitidos, 0 fallidos"
    with Image.open(c.carpeta_salida / "a.jpg") as im:
        assert im.format == "JPEG" and im.size == (64, 48)
    assert (c.carpeta_salida / "viaje" / "b.jpg").is_file()


def test_fichero_corrupto_no_detiene_el_lote(ctx):
    c = ctx(BASE)
    heic(c.carpeta_entrada / "bien.heic")
    (c.carpeta_entrada / "roto.heic").write_bytes(b"esto no es una imagen")
    informe = ejecutar(c)
    assert len(informe.resultados) == 1 and len(informe.fallos) == 1
    assert informe.fallos[0]["elemento"] == "roto.heic" and "dañado" in informe.fallos[0]["motivo"]
    assert not list(c.carpeta_temporal.iterdir())  # sin restos a medias


def test_otros_tipos_se_omiten(ctx):
    c = ctx(BASE)
    heic(c.carpeta_entrada / "a.heic")
    (c.carpeta_entrada / "notas.txt").write_text("hola")
    informe = ejecutar(c)
    assert [o["elemento"] for o in informe.omitidos] == ["notas.txt"] and len(informe.resultados) == 1


def test_calidad_cambia_el_tamano(ctx, tmp_path):
    c = ctx({**BASE, "calidad": 95})
    heic(c.carpeta_entrada / "a.heic", tam=(300, 300))
    # Imagen con ruido para que la compresión importe
    import random
    im = Image.new("RGB", (300, 300))
    im.putdata([(random.randrange(256),) * 3 for _ in range(300 * 300)])
    im.save(c.carpeta_entrada / "a.heic", quality=90)
    alta = ejecutar(c).resultados[0]["bytes"]
    c2 = ctx({**BASE, "calidad": 20})
    (c2.carpeta_salida / "a.jpg").unlink()
    baja = ejecutar(c2).resultados[0]["bytes"]
    assert baja < alta


def test_redimensionar(ctx):
    c = ctx({**BASE, "redimensionar": 32})
    heic(c.carpeta_entrada / "a.heic", tam=(64, 48))
    ejecutar(c)
    with Image.open(c.carpeta_salida / "a.jpg") as im:
        assert im.size == (32, 24)


def test_metadatos_y_gps(ctx):
    def convertir(**opciones):
        c = ctx({**BASE, **opciones})
        for f in c.carpeta_salida.glob("*"):
            f.unlink()
        heic(c.carpeta_entrada / "a.heic", exif=exif_con_gps())
        ejecutar(c)
        with Image.open(c.carpeta_salida / "a.jpg") as im:
            e = im.getexif()
            return e.get(0x010F), bool(e.get_ifd(0x8825))

    assert convertir(conservar_metadatos=True, quitar_gps=False) == ("MarcaPrueba", True)
    assert convertir(conservar_metadatos=True, quitar_gps=True) == ("MarcaPrueba", False)
    assert convertir(conservar_metadatos=False, quitar_gps=False) == (None, False)


@pytest.mark.parametrize("modo, esperado", [
    ("numerar", {"a.jpg", "a (1).jpg"}), ("sobrescribir", {"a.jpg"}), ("omitir", {"a.jpg"})])
def test_nombre_repetido(ctx, modo, esperado):
    c = ctx({**BASE, "si_existe": modo})
    heic(c.carpeta_entrada / "a.heic")
    heic(c.carpeta_entrada / "a.heif")  # ambos darían a.jpg
    informe = ejecutar(c)
    assert {p.name for p in c.carpeta_salida.iterdir()} == esperado
    assert len(informe.omitidos) == (1 if modo == "omitir" else 0)


def test_sin_ficheros_da_error_de_usuario(ctx):
    with pytest.raises(ErrorUsuario):
        ejecutar(ctx(BASE))


def test_cancelacion(ctx):
    c = ctx(BASE)
    heic(c.carpeta_entrada / "a.heic")
    c.bandera_cancelacion.set()
    with pytest.raises(Cancelado):
        ejecutar(c)
