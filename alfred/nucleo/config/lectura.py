"""Lectura y validación de la configuración del servidor."""
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

RUTA_POR_DEFECTO = Path("config/servidor.toml")


class ErrorConfig(Exception):
    pass


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    url_bd: str
    zona_temporal: Path
    max_ligeros: int = 4
    max_pesados: int = 1
    gracia_cancelacion_s: float = 10.0
    conservacion_horas: float = 6.0
    limpieza_cada_minutos: float = 10.0


def ruta_config() -> Path:
    return Path(os.environ.get("ALFRED_CONFIG", RUTA_POR_DEFECTO))


def cargar(ruta: Path | None = None) -> Config:
    ruta = ruta or ruta_config()
    if not ruta.is_file():
        raise ErrorConfig(
            f"No existe {ruta}. Copia config.ejemplo/servidor.ejemplo.toml a esa ruta."
        )
    try:
        datos = tomllib.loads(ruta.read_text(encoding="utf-8"))
        trabajos = datos.get("trabajos", {})
        almacen = datos.get("almacenamiento", {})
        conservacion = float(almacen.get("conservacion_horas", 6))
        cada = float(almacen.get("limpieza_cada_minutos", 10))
        if conservacion < 0:
            raise ValueError("almacenamiento.conservacion_horas no puede ser negativo (0 = no caducan)")
        if cada <= 0:
            raise ValueError("almacenamiento.limpieza_cada_minutos debe ser mayor que 0")
        return Config(
            host=datos["servidor"].get("host", "127.0.0.1"),
            port=int(datos["servidor"].get("port", 8000)),
            url_bd=datos["base_datos"]["url"],
            zona_temporal=Path(
                datos.get("almacenamiento", {}).get("zona_temporal", "datos/temporal")
            ),
            max_ligeros=int(trabajos.get("max_ligeros", 4)),
            max_pesados=int(trabajos.get("max_pesados", 1)),
            gracia_cancelacion_s=float(trabajos.get("gracia_cancelacion_s", 10)),
            conservacion_horas=conservacion,
            limpieza_cada_minutos=cada,
        )
    except (tomllib.TOMLDecodeError, KeyError, ValueError) as e:
        raise ErrorConfig(f"Configuración inválida en {ruta}: {e!r}") from e
