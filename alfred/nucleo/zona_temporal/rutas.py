"""Carpeta aislada de cada trabajo dentro de la zona temporal.

    <zona>/<id>/
        entrada/       ficheros de entrada (no se borra al reintentar)
        temporal/      temporales del minijob (se vacía en cada ejecución)
        salida/        resultados descargables
        entradas.json, informe.json, error.json, salida.log   (control)
"""
import json
import os
import shutil
import uuid
import zipfile
from pathlib import Path

from alfred.comun.contrato import ENTRADAS, ERROR, INFORME, LOG


ZIP = "resultado.zip"


def carpeta_trabajo(zona: Path, trabajo_id: uuid.UUID) -> Path:
    return zona / str(trabajo_id)


def preparar_ejecucion(carpeta: Path, entradas: dict) -> None:
    carpeta.mkdir(parents=True, exist_ok=True, mode=0o700)
    for sub in ("temporal", "salida"):
        shutil.rmtree(carpeta / sub, ignore_errors=True)
    for nombre in (INFORME, ERROR, LOG, ZIP):
        (carpeta / nombre).unlink(missing_ok=True)
    for sub in ("entrada", "temporal", "salida"):
        (carpeta / sub).mkdir(exist_ok=True)
    (carpeta / ENTRADAS).write_text(json.dumps(entradas, ensure_ascii=False), encoding="utf-8")


def borrar(carpeta: Path) -> None:
    shutil.rmtree(carpeta, ignore_errors=True)


def listar_salida(carpeta: Path) -> list[tuple[str, int]]:
    """(ruta relativa, bytes) de los resultados descargables, ordenados."""
    base = carpeta / "salida"
    if not base.is_dir():
        return []
    return sorted((p.relative_to(base).as_posix(), p.stat().st_size) for p in base.rglob("*") if p.is_file())


def ruta_segura(base: Path, relativa: str) -> Path | None:
    """Resuelve `relativa` dentro de `base`; None si intenta salirse (p. ej. con '..')."""
    base = base.resolve()
    destino = (base / relativa).resolve()
    return destino if base in destino.parents else None


def crear_zip(carpeta: Path) -> Path:
    """ZIP de los resultados (sin recomprimir: los JPG ya están comprimidos). Se crea una vez."""
    destino = carpeta / ZIP
    if destino.is_file():
        return destino
    temporal = carpeta / f"{ZIP}.{uuid.uuid4().hex}.tmp"
    with zipfile.ZipFile(temporal, "w", zipfile.ZIP_STORED) as z:
        for relativa, _ in listar_salida(carpeta):
            z.write(carpeta / "salida" / relativa, relativa)
    os.replace(temporal, destino)  # atómico: nunca se sirve un zip a medias
    return destino
