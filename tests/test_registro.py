from pathlib import Path

import alfred.nucleo.minijobs.registro as reg

BASE = 'id="{id}"\nnombre="N"\ndescripcion="d"\ncategoria="c"\nversion="1"\npeso="{peso}"\ntiempo_maximo={t}\n'


def _minijob(raiz: Path, id: str, *, carpeta: str | None = None, peso="ligero", t=60, ejecutar=True):
    carpeta = raiz / (carpeta or id)
    carpeta.mkdir(parents=True)
    (carpeta / "manifiesto.toml").write_text(BASE.format(id=id, peso=peso, t=t), encoding="utf-8")
    if ejecutar:
        (carpeta / "ejecutar.py").write_text("", encoding="utf-8")


def _descubrir(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "_carpetas_base", lambda: [tmp_path])
    return reg.descubrir()


def test_descubre_valido_e_ignora_incompleto(tmp_path, monkeypatch):
    _minijob(tmp_path, "ok")
    (tmp_path / "roto").mkdir()
    (tmp_path / "roto" / "manifiesto.toml").write_text('id="roto"\n', encoding="utf-8")
    validos, avisos = _descubrir(tmp_path, monkeypatch)
    assert [m.id for m in validos] == ["ok"]
    assert validos[0].peso == "ligero" and validos[0].tiempo_maximo_s == 60
    assert len(avisos) == 1 and "faltan campos" in avisos[0]


def test_rechaza_peso_invalido(tmp_path, monkeypatch):
    _minijob(tmp_path, "x", peso="enorme")
    validos, avisos = _descubrir(tmp_path, monkeypatch)
    assert not validos and "peso inválido" in avisos[0]


def test_rechaza_id_distinto_de_la_carpeta(tmp_path, monkeypatch):
    _minijob(tmp_path, "uno", carpeta="otro")
    validos, avisos = _descubrir(tmp_path, monkeypatch)
    assert not validos and "debe coincidir" in avisos[0]


def test_rechaza_tiempo_maximo_invalido_y_falta_de_ejecutar(tmp_path, monkeypatch):
    _minijob(tmp_path, "a", t=0)
    _minijob(tmp_path, "b", ejecutar=False)
    validos, avisos = _descubrir(tmp_path, monkeypatch)
    assert not validos and len(avisos) == 2


def test_dependencias_faltantes(monkeypatch):
    import importlib.util
    from alfred.nucleo.arranque import requisitos

    monkeypatch.setattr(importlib.util, "find_spec", lambda nombre: None)
    r = requisitos.comprobar_dependencias()
    assert not r.ok and "pip install -e ." in r.mensaje
