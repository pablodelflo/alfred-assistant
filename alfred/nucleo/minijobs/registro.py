"""Registro de minijobs: descubre y valida los manifiestos."""
import tomllib
from dataclasses import dataclass
from pathlib import Path

import alfred.minijobs as paquete_minijobs

CAMPOS_OBLIGATORIOS = ("id", "nombre", "descripcion", "categoria", "version", "peso", "tiempo_maximo")
PESOS = ("ligero", "pesado")


@dataclass(frozen=True)
class Minijob:
    id: str
    nombre: str
    descripcion: str
    categoria: str
    version: str
    peso: str
    tiempo_maximo_s: int
    ruta: Path  # carpeta del minijob


def _carpetas_base() -> list[Path]:
    base = Path(paquete_minijobs.__file__).parent
    return [base, Path("minijobs_personales")]


def _leer(manifiesto: Path) -> Minijob:
    datos = tomllib.loads(manifiesto.read_text(encoding="utf-8"))
    faltan = [c for c in CAMPOS_OBLIGATORIOS if c not in datos]
    if faltan:
        raise ValueError(f"faltan campos: {', '.join(faltan)}")
    carpeta = manifiesto.parent
    if datos["id"] != carpeta.name:
        raise ValueError(f"el id «{datos['id']}» debe coincidir con el nombre de la carpeta «{carpeta.name}»")
    if datos["peso"] not in PESOS:
        raise ValueError(f"peso inválido «{datos['peso']}» (usa: {', '.join(PESOS)})")
    tiempo = datos["tiempo_maximo"]
    if not isinstance(tiempo, int) or isinstance(tiempo, bool) or tiempo <= 0:
        raise ValueError("tiempo_maximo debe ser un entero positivo de segundos")
    if not (carpeta / "ejecutar.py").is_file():
        raise ValueError("falta ejecutar.py")
    return Minijob(id=datos["id"], nombre=datos["nombre"], descripcion=datos["descripcion"],
                   categoria=datos["categoria"], version=datos["version"], peso=datos["peso"],
                   tiempo_maximo_s=tiempo, ruta=carpeta.resolve())


def descubrir() -> tuple[list[Minijob], list[str]]:
    """Devuelve (minijobs válidos, avisos de los inválidos)."""
    validos, avisos = [], []
    for carpeta in _carpetas_base():
        if not carpeta.is_dir():
            continue
        for manifiesto in sorted(carpeta.glob("*/manifiesto.toml")):
            try:
                validos.append(_leer(manifiesto))
            except Exception as e:
                avisos.append(f"{manifiesto}: {e}")
    return validos, avisos
