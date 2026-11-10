"""Carpeta aislada de cada trabajo dentro de la zona temporal.

    <zona>/<id>/
        entrada/       ficheros de entrada (no se borra al reintentar)
        temporal/      temporales del minijob (se vacía en cada ejecución)
        salida/        resultados descargables
        entradas.json, informe.json, error.json, salida.log   (control)
"""
import json
import shutil
import uuid
from pathlib import Path

from alfred.comun.contrato import ENTRADAS, ERROR, INFORME, LOG


def carpeta_trabajo(zona: Path, trabajo_id: uuid.UUID) -> Path:
    return zona / str(trabajo_id)


def preparar_ejecucion(carpeta: Path, entradas: dict) -> None:
    carpeta.mkdir(parents=True, exist_ok=True, mode=0o700)
    for sub in ("temporal", "salida"):
        shutil.rmtree(carpeta / sub, ignore_errors=True)
    for nombre in (INFORME, ERROR, LOG):
        (carpeta / nombre).unlink(missing_ok=True)
    for sub in ("entrada", "temporal", "salida"):
        (carpeta / sub).mkdir(exist_ok=True)
    (carpeta / ENTRADAS).write_text(json.dumps(entradas, ensure_ascii=False), encoding="utf-8")


def borrar(carpeta: Path) -> None:
    shutil.rmtree(carpeta, ignore_errors=True)
