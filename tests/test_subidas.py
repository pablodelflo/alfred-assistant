import io

import pytest

from alfred.nucleo.zona_temporal.rutas import crear_zip, listar_salida, ruta_segura
from alfred.nucleo.zona_temporal.subidas import ErrorSubida, guardar_subidas, nombre_seguro

LIM = dict(max_fichero_mb=1, max_lote_mb=2, max_ficheros=10)


def f(contenido=b"x"):
    return io.BytesIO(contenido)


@pytest.mark.parametrize("bruto, esperado", [
    ("foto.heic", "foto.heic"), ("viaje/dia 1/foto.heic", "viaje/dia 1/foto.heic"),
    ("C:\\fotos\\a.heic", "C:/fotos/a.heic"), ("/etc/passwd", "etc/passwd"), ("./a.heic", "a.heic"),
    ("a\x00b.heic", "ab.heic"), ("../secreto", None), ("a/../../b", None), ("", None), ("///", None)])
def test_nombre_seguro(bruto, esperado):
    assert nombre_seguro(bruto) == esperado


def test_guarda_conservando_subcarpetas(tmp_path):
    nombres, ign = guardar_subidas([("a.heic", f()), ("viaje/b.heic", f())], tmp_path / "e", **LIM)
    assert nombres == ["a.heic", "viaje/b.heic"] and ign == 0
    assert (tmp_path / "e" / "viaje" / "b.heic").is_file()


def test_nombres_repetidos_se_numeran_y_no_se_pisan(tmp_path):
    nombres, _ = guardar_subidas([("a.heic", f(b"1")), ("a.heic", f(b"2"))], tmp_path / "e", **LIM)
    assert nombres == ["a.heic", "a (1).heic"]
    assert (tmp_path / "e" / "a.heic").read_bytes() == b"1"


def test_filtra_por_extension(tmp_path):
    nombres, ign = guardar_subidas([("a.HEIC", f()), ("notas.txt", f())], tmp_path / "e", extensiones=(".heic",), **LIM)
    assert nombres == ["a.HEIC"] and ign == 1


def test_limite_por_fichero(tmp_path):
    with pytest.raises(ErrorSubida, match="por fichero"):
        guardar_subidas([("g.heic", f(b"0" * (1024 * 1024 + 1)))], tmp_path / "e", **LIM)


def test_limite_por_lote(tmp_path):
    grandes = [(f"{i}.heic", f(b"0" * 900_000)) for i in range(3)]  # 2,6 MB > 2 MB
    with pytest.raises(ErrorSubida, match="por lote"):
        guardar_subidas(grandes, tmp_path / "e", **LIM)


def test_limite_de_numero_de_ficheros(tmp_path):
    with pytest.raises(ErrorSubida, match="Demasiados"):
        guardar_subidas([(f"{i}.heic", f()) for i in range(11)], tmp_path / "e", **LIM)


def test_nombre_malicioso_se_rechaza(tmp_path):
    with pytest.raises(ErrorSubida, match="no válido"):
        guardar_subidas([("../../escapar.heic", f())], tmp_path / "e", **LIM)
    assert not (tmp_path / "escapar.heic").exists()


def test_ruta_segura(tmp_path):
    (tmp_path / "salida").mkdir()
    (tmp_path / "secreto.txt").write_text("no")
    (tmp_path / "salida" / "ok.jpg").write_text("si")
    base = tmp_path / "salida"
    assert ruta_segura(base, "ok.jpg") == (base / "ok.jpg").resolve()
    assert ruta_segura(base, "../secreto.txt") is None
    assert ruta_segura(base, "/etc/passwd") is None


def test_listar_y_zip(tmp_path):
    (tmp_path / "salida" / "viaje").mkdir(parents=True)
    (tmp_path / "salida" / "a.jpg").write_bytes(b"aa")
    (tmp_path / "salida" / "viaje" / "b.jpg").write_bytes(b"bbb")
    assert listar_salida(tmp_path) == [("a.jpg", 2), ("viaje/b.jpg", 3)]
    import zipfile
    with zipfile.ZipFile(crear_zip(tmp_path)) as z:
        assert sorted(z.namelist()) == ["a.jpg", "viaje/b.jpg"]
    assert crear_zip(tmp_path) == tmp_path / "resultado.zip"  # se reutiliza
