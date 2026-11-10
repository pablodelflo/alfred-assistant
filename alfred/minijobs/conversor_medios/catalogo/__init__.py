"""Catálogo de conversiones: una entrada por conversión.

Para añadir una (p. ej. mp3): crear su módulo aquí, registrarla abajo y añadir su opción
al `manifiesto.toml` con sus dependencias.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class Conversion:
    id: str
    extensiones_entrada: tuple[str, ...]
    extension_salida: str
    convertir: Callable[[Path, Path, dict], None]  # (origen, destino, opciones)


from .heic_a_jpg import CONVERSION as _HEIC_A_JPG  # noqa: E402

CATALOGO: dict[str, Conversion] = {c.id: c for c in (_HEIC_A_JPG,)}
