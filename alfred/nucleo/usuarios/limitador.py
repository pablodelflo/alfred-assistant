"""Límite de intentos de acceso fallidos. En memoria: se reinicia al reiniciar Alfred."""
import threading
import time


class LimitadorIntentos:
    def __init__(self, reloj=time.monotonic):
        self._reloj = reloj
        self._fallos: dict[str, list[float]] = {}
        self._cerrojo = threading.Lock()

    def _recientes(self, clave: str, ventana_s: float) -> list[float]:
        limite = self._reloj() - ventana_s
        vivos = [t for t in self._fallos.get(clave, []) if t > limite]
        self._fallos[clave] = vivos
        return vivos

    def segundos_de_bloqueo(self, claves: list[str], maximo: int, ventana_s: float) -> int:
        """0 si se puede intentar; si no, los segundos que faltan para el desbloqueo."""
        with self._cerrojo:
            restante = 0.0
            for clave in claves:
                vivos = self._recientes(clave, ventana_s)
                if len(vivos) >= maximo:
                    restante = max(restante, vivos[-maximo] + ventana_s - self._reloj())
            return int(restante) + 1 if restante > 0 else 0

    def fallo(self, claves: list[str]) -> None:
        with self._cerrojo:
            for clave in claves:
                self._fallos.setdefault(clave, []).append(self._reloj())

    def exito(self, claves: list[str]) -> None:
        with self._cerrojo:
            for clave in claves:
                self._fallos.pop(clave, None)
