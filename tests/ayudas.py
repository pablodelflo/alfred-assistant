from fastapi.testclient import TestClient

from alfred.nucleo.usuarios import servicio

CLAVE = "una-clave-larga-123"


def cliente_web(app, **cabeceras) -> TestClient:
    """Cliente que, como un navegador, envía Origin en sus formularios."""
    return TestClient(app, base_url="http://testserver", headers={"Origin": "http://testserver", **cabeceras})


def iniciar_sesion(cliente, sesiones, nombre="admin", clave=CLAVE):
    with sesiones() as s:
        if not servicio.hay_usuarios(s):
            servicio.crear_usuario(s, nombre, clave)
            s.commit()
    r = cliente.post("/entrar", data={"usuario": nombre, "clave": clave}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return r
