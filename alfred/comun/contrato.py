"""Contrato de ejecución del minijob (lo único que un minijob necesita importar).

Un minijob es una carpeta con `manifiesto.toml` y `ejecutar.py`, que define:

    def ejecutar(ctx: Contexto) -> Informe: ...
"""
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# Nombres de los ficheros de control dentro de la carpeta de cada trabajo.
ENTRADAS = "entradas.json"
INFORME = "informe.json"
ERROR = "error.json"
LOG = "salida.log"

# Las líneas de la salida estándar que empiezan por este prefijo son mensajes al núcleo.
PROTOCOLO = "@@alfred@@ "

# Código de salida del proceso cuando el minijob se detuvo por una cancelación.
EXIT_CANCELADO = 3


class ErrorUsuario(Exception):
    """Error con un mensaje claro para el usuario. El detalle técnico va al log."""


class Cancelado(Exception):
    """Se pidió cancelar el trabajo."""


@dataclass
class Informe:
    resumen: str
    resultados: list[dict] = field(default_factory=list)
    fallos: list[dict] = field(default_factory=list)  # fallos parciales: no detienen el lote
    omitidos: list[dict] = field(default_factory=list)  # no se procesaron a propósito


def _imprimir(linea: str) -> None:
    print(PROTOCOLO + linea, flush=True)


@dataclass
class Contexto:
    entradas: dict
    carpeta_entrada: Path   # ficheros de entrada; solo lectura por convención
    carpeta_temporal: Path  # único sitio donde escribir temporales (se vacía en cada ejecución)
    carpeta_salida: Path    # resultados que el usuario podrá descargar
    bandera_cancelacion: threading.Event = field(default_factory=threading.Event, repr=False)
    _emitir: Callable[[str], None] = field(default=_imprimir, repr=False)

    def progreso(self, porcentaje: int, mensaje: str = "") -> None:
        porcentaje = max(0, min(100, int(porcentaje)))
        self._emitir(json.dumps({"tipo": "progreso", "porcentaje": porcentaje,
                                 "mensaje": mensaje[:300]}, ensure_ascii=False))

    def cancelado(self) -> bool:
        return self.bandera_cancelacion.is_set()

    def comprobar_cancelacion(self) -> None:
        """Lanza Cancelado si se pidió cancelar. Llamar a menudo desde el bucle del minijob."""
        if self.cancelado():
            raise Cancelado()
