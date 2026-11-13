import pytest

from alfred.nucleo.usuarios import claves


@pytest.fixture(autouse=True)
def hash_barato(monkeypatch):
    """scrypt con coste bajo para que los tests vayan rápido (el real se comprueba en test_acceso)."""
    monkeypatch.setattr(claves, "N_LOG2", 10)
