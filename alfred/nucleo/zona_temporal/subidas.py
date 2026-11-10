"""Guardado seguro en disco de los ficheros subidos desde el navegador."""
import re
import shutil
from pathlib import Path
from typing import BinaryIO

MB = 1024 * 1024
TROZO = 1024 * 1024
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class ErrorSubida(Exception):
    """Mensaje claro para el usuario."""


def nombre_seguro(bruto: str) -> str | None:
    """Ruta relativa limpia (sin '..', sin absolutas, sin caracteres de control) o None."""
    partes = []
    for parte in bruto.replace("\\", "/").split("/"):
        parte = _CONTROL.sub("", parte).strip()
        if parte in ("", "."):
            continue
        if parte == "..":
            return None
        partes.append(parte[:200])
    return "/".join(partes) or None


def nombre_libre(ruta: Path) -> Path:
    if not ruta.exists():
        return ruta
    n = 1
    while True:
        candidato = ruta.with_name(f"{ruta.stem} ({n}){ruta.suffix}")
        if not candidato.exists():
            return candidato
        n += 1


def guardar_subidas(archivos: list[tuple[str, BinaryIO]], destino: Path, *, max_fichero_mb: float,
                    max_lote_mb: float, max_ficheros: int,
                    extensiones: tuple[str, ...] = ()) -> tuple[list[str], int]:
    """Copia los ficheros a `destino` por trozos, respetando los límites.

    Devuelve (nombres guardados, cuántos se ignoraron por su extensión).
    Lanza ErrorSubida al superar un límite; quien llama debe borrar lo copiado.
    """
    if len(archivos) > max_ficheros:
        raise ErrorSubida(f"Demasiados ficheros: {len(archivos)} (máximo {max_ficheros}).")
    limite_fichero, limite_lote = int(max_fichero_mb * MB), int(max_lote_mb * MB)
    guardados, ignorados, total = [], 0, 0
    destino.mkdir(parents=True, exist_ok=True)
    for bruto, origen in archivos:
        nombre = nombre_seguro(bruto)
        if nombre is None:
            raise ErrorSubida(f"Nombre de fichero no válido: «{bruto[:80]}».")
        if extensiones and not nombre.lower().endswith(extensiones):
            ignorados += 1
            continue
        ruta = nombre_libre(destino / nombre)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        tamano = 0
        with open(ruta, "wb") as salida:
            while trozo := origen.read(TROZO):
                tamano += len(trozo)
                total += len(trozo)
                if tamano > limite_fichero:
                    raise ErrorSubida(f"«{nombre}» supera el máximo por fichero ({max_fichero_mb:g} MB).")
                if total > limite_lote:
                    raise ErrorSubida(f"La subida supera el máximo por lote ({max_lote_mb:g} MB).")
                salida.write(trozo)
        guardados.append(str(ruta.relative_to(destino)))
    return guardados, ignorados


def espacio_libre(carpeta: Path) -> int:
    carpeta.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(carpeta).free
