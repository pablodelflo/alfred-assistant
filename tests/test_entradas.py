import pytest

from alfred.nucleo.minijobs.entradas import (parsear_campos, problemas_de_disponibilidad, validar)

CAMPOS = parsear_campos([
    {"id": "calidad", "tipo": "entero", "etiqueta": "Calidad", "defecto": 90, "minimo": 1, "maximo": 100},
    {"id": "gps", "tipo": "booleano", "etiqueta": "GPS"},
    {"id": "modo", "tipo": "seleccion", "etiqueta": "Modo", "obligatorio": True, "defecto": "a",
     "opciones": [{"valor": "a", "etiqueta": "A"}, {"valor": "b", "etiqueta": "B"},
                  {"valor": "c", "etiqueta": "C", "dependencias": ["modulo_que_no_existe_xyz"]}]},
    {"id": "fotos", "tipo": "ficheros", "etiqueta": "Fotos", "obligatorio": True, "extensiones": [".HEIC"]},
])


def test_valida_y_aplica_valores_por_defecto():
    v = validar(CAMPOS, {})
    assert v.ok and v.valores == {"calidad": 90, "gps": False, "modo": "a"}


def test_convierte_tipos():
    v = validar(CAMPOS, {"calidad": " 75 ", "gps": "on", "modo": "b"})
    assert v.ok and v.valores == {"calidad": 75, "gps": True, "modo": "b"}


@pytest.mark.parametrize("calidad", ["0", "101", "abc", "7.5"])
def test_entero_fuera_de_rango_o_invalido(calidad):
    assert "calidad" in validar(CAMPOS, {"calidad": calidad}).errores


def test_opcion_inexistente_o_sin_dependencias_se_rechaza():
    assert "modo" in validar(CAMPOS, {"modo": "z"}).errores
    assert "modo" in validar(CAMPOS, {"modo": "c"}).errores  # existe, pero no está disponible aquí


def test_las_opciones_no_disponibles_no_se_ofrecen():
    modo = next(c for c in CAMPOS if c.id == "modo")
    assert [o.valor for o in modo.opciones_disponibles] == ["a", "b"]


def test_extensiones_se_normalizan_a_minusculas():
    assert next(c for c in CAMPOS if c.id == "fotos").extensiones == (".heic",)


def test_manifiesto_invalido():
    for malo in ([{"id": "x", "tipo": "raro", "etiqueta": "X"}],
                 [{"id": "x", "tipo": "seleccion", "etiqueta": "X"}],
                 [{"id": "x", "tipo": "entero", "etiqueta": "X"}, {"id": "x", "tipo": "entero", "etiqueta": "Y"}],
                 [{"tipo": "entero", "etiqueta": "X"}]):
        with pytest.raises(ValueError):
            parsear_campos(malo)


def test_seleccion_obligatoria_sin_opciones_disponibles_es_un_problema():
    campos = parsear_campos([{"id": "m", "tipo": "seleccion", "etiqueta": "Modo", "obligatorio": True,
                              "opciones": [{"valor": "a", "etiqueta": "A", "dependencias": ["no_existe_abc"]}]}])
    assert "no_existe_abc" in problemas_de_disponibilidad(campos)[0]
