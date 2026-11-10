"""Proceso de trabajo: python -m alfred.nucleo.trabajos.proceso CARPETA_TRABAJO CARPETA_MINIJOB

No toca la base de datos: lee `entradas.json`, informa del progreso por la salida
estándar y deja `informe.json` (o `error.json`) en la carpeta del trabajo.
Solo depende de alfred.comun.
"""
import importlib
import json
import signal
import sys
import threading
import traceback
from pathlib import Path

from alfred.comun.contrato import (EXIT_CANCELADO, ENTRADAS, ERROR, INFORME, Cancelado,
                                   Contexto, ErrorUsuario, Informe)


def _escribir(carpeta: Path, nombre: str, datos: dict) -> None:
    (carpeta / nombre).write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")


def principal(carpeta: Path, carpeta_minijob: Path) -> int:
    bandera = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: bandera.set())

    try:
        entradas = json.loads((carpeta / ENTRADAS).read_text(encoding="utf-8"))
        ctx = Contexto(entradas=entradas,
                       carpeta_entrada=carpeta / "entrada",
                       carpeta_temporal=carpeta / "temporal",
                       carpeta_salida=carpeta / "salida",
                       bandera_cancelacion=bandera)
        sys.path.insert(0, str(carpeta_minijob.parent))
        modulo = importlib.import_module(f"{carpeta_minijob.name}.ejecutar")
        informe = modulo.ejecutar(ctx)
        if not isinstance(informe, Informe):
            raise TypeError("ejecutar() debe devolver un Informe")
        _escribir(carpeta, INFORME, {"resumen": informe.resumen,
                                     "resultados": informe.resultados,
                                     "fallos": informe.fallos,
                                     "omitidos": informe.omitidos})
        return 0
    except Cancelado:
        return EXIT_CANCELADO
    except ErrorUsuario as e:
        _escribir(carpeta, ERROR, {"usuario": str(e), "tecnico": traceback.format_exc()})
        return 1
    except BaseException:
        _escribir(carpeta, ERROR, {"usuario": "El minijob falló de forma inesperada.",
                                   "tecnico": traceback.format_exc()})
        return 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("Uso: python -m alfred.nucleo.trabajos.proceso CARPETA_TRABAJO CARPETA_MINIJOB")
    sys.exit(principal(Path(sys.argv[1]), Path(sys.argv[2])))
