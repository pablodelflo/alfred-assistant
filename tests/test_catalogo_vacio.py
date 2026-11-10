from fastapi.testclient import TestClient

from alfred.nucleo.web.app import crear_app


def test_inicio_muestra_catalogo_vacio():
    r = TestClient(crear_app()).get("/")
    assert r.status_code == 200
    assert "Todavía no hay minijobs" in r.text


def test_acerca_de_muestra_aviso():
    r = TestClient(crear_app()).get("/acerca-de")
    assert r.status_code == 200
    assert "GPL-3.0" in r.text


def test_el_ciclo_de_vida_arranca_y_para_el_lanzador():
    class Falso:
        eventos = []
        def start(self): self.eventos.append("start")
        def stop(self): self.eventos.append("stop")

    falso = Falso()
    with TestClient(crear_app(falso)):
        assert falso.eventos == ["start"]
    assert falso.eventos == ["start", "stop"]
