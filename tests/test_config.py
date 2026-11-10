import pytest

from alfred.nucleo.config.lectura import ErrorConfig, cargar

BASE = '[base_datos]\nurl = "postgresql://a:b@localhost/c"\n[servidor]\n'


def _cfg(tmp_path, extra=""):
    ruta = tmp_path / "servidor.toml"
    ruta.write_text(BASE + extra, encoding="utf-8")
    return ruta


def test_valores_por_defecto(tmp_path):
    c = cargar(_cfg(tmp_path))
    assert c.conservacion_horas == 6 and c.limpieza_cada_minutos == 10
    assert (c.max_ligeros, c.max_pesados, c.gracia_cancelacion_s) == (4, 1, 10)


def test_conservacion_configurable(tmp_path):
    c = cargar(_cfg(tmp_path, '[almacenamiento]\nconservacion_horas = 48\nlimpieza_cada_minutos = 5\n'))
    assert c.conservacion_horas == 48 and c.limpieza_cada_minutos == 5


def test_cero_significa_que_no_caducan(tmp_path):
    assert cargar(_cfg(tmp_path, '[almacenamiento]\nconservacion_horas = 0\n')).conservacion_horas == 0


@pytest.mark.parametrize("extra", ['[almacenamiento]\nconservacion_horas = -1\n',
                                   '[almacenamiento]\nlimpieza_cada_minutos = 0\n'])
def test_valores_invalidos(tmp_path, extra):
    with pytest.raises(ErrorConfig):
        cargar(_cfg(tmp_path, extra))
