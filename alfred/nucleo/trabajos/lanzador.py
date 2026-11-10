"""Lanzador: arranca y vigila los procesos de trabajo. Es quien cambia los estados."""
import json
import logging
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

import alfred
from alfred.comun.contrato import ERROR, INFORME, LOG, PROTOCOLO
from alfred.nucleo.actividad.registro import registrar
from alfred.nucleo.datos.modelos import Trabajo
from alfred.nucleo.minijobs import registro
from alfred.nucleo.minijobs.registro import Minijob
from alfred.nucleo.trabajos.estados import Estado
from alfred.nucleo.trabajos.servicio import cambiar_estado
from alfred.nucleo.zona_temporal.rutas import borrar, carpeta_trabajo, preparar_ejecucion

log = logging.getLogger("alfred.lanzador")
RAIZ_PAQUETE = str(Path(alfred.__file__).resolve().parents[1])


def _leer_salida(flujo, cola: queue.Queue, ruta_log: Path) -> None:
    """Separa los mensajes del protocolo del resto de la salida (que va a salida.log)."""
    with open(ruta_log, "a", encoding="utf-8", errors="replace") as fichero:
        for linea in flujo:
            if linea.startswith(PROTOCOLO):
                try:
                    cola.put(json.loads(linea[len(PROTOCOLO):]))
                    continue
                except ValueError:
                    pass
            fichero.write(linea)
            fichero.flush()


def _leer_json(ruta: Path) -> dict | None:
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _cola_del_log(ruta: Path, caracteres: int = 2000) -> str:
    try:
        return ruta.read_text(encoding="utf-8", errors="replace")[-caracteres:]
    except OSError:
        return ""


@dataclass
class _Activo:
    popen: subprocess.Popen
    minijob: Minijob
    inicio: float
    cola: queue.Queue
    lector: threading.Thread
    ultimo_progreso: tuple[int, str] | None = None
    t_term: float | None = None   # cuándo se envió SIGTERM
    kill_enviado: bool = False
    por_tiempo: bool = False


def _senal(activo: _Activo, senal: int) -> None:
    try:
        os.killpg(activo.popen.pid, senal)
    except ProcessLookupError:
        pass


class Lanzador:
    def __init__(self, sesiones: sessionmaker[Session], zona_temporal: Path, *,
                 max_ligeros: int = 4, max_pesados: int = 1,
                 gracia_cancelacion_s: float = 10.0, intervalo_s: float = 1.0):
        self._sesiones = sesiones
        self.zona = zona_temporal
        self._maximos = {"ligero": max_ligeros, "pesado": max_pesados}
        self.gracia_s = gracia_cancelacion_s
        self.intervalo_s = intervalo_s
        self._activos: dict = {}
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None

    # ---- ciclo de vida del hilo supervisor ----
    def start(self) -> None:
        self._parar.clear()
        self._hilo = threading.Thread(target=self._bucle, name="lanzador", daemon=True)
        self._hilo.start()

    def stop(self) -> None:
        self._parar.set()
        if self._hilo:
            self._hilo.join(timeout=self.gracia_s + 5)
        self._interrumpir_activos()

    def _bucle(self) -> None:
        while not self._parar.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("Error en el lanzador")
            self._parar.wait(self.intervalo_s)

    # ---- una vuelta de supervisión ----
    def tick(self) -> None:
        for trabajo_id in list(self._activos):
            self._atender(trabajo_id)
        self._lanzar_pendientes()

    def _atender(self, trabajo_id) -> None:
        activo = self._activos[trabajo_id]
        try:
            with self._sesiones() as s:
                trabajo = s.get(Trabajo, trabajo_id, with_for_update=True)
                ultimo = None
                while True:
                    try:
                        ultimo = activo.cola.get_nowait()
                    except queue.Empty:
                        break
                if ultimo and ultimo.get("tipo") == "progreso":
                    marca = (int(ultimo["porcentaje"]), str(ultimo.get("mensaje", "")))
                    if marca != activo.ultimo_progreso:
                        trabajo.progreso, trabajo.mensaje_progreso = marca[0], marca[1] or None
                        activo.ultimo_progreso = marca
                codigo = activo.popen.poll()
                if codigo is None:
                    self._vigilar(trabajo, activo)
                else:
                    self._finalizar(s, trabajo, activo, codigo)
                    del self._activos[trabajo_id]
                s.commit()
        except Exception:
            log.exception("Error atendiendo el trabajo %s", trabajo_id)
            if activo.popen.poll() is not None:
                self._activos.pop(trabajo_id, None)

    def _vigilar(self, trabajo: Trabajo, activo: _Activo) -> None:
        ahora = time.monotonic()
        if activo.t_term is None:
            if trabajo.estado == Estado.CANCELANDOSE.value:
                _senal(activo, signal.SIGTERM)
                activo.t_term = ahora
            elif ahora - activo.inicio > activo.minijob.tiempo_maximo_s:
                activo.por_tiempo = True
                _senal(activo, signal.SIGTERM)
                activo.t_term = ahora
        elif not activo.kill_enviado and ahora - activo.t_term > self.gracia_s:
            _senal(activo, signal.SIGKILL)  # el minijob no respondió: se corta
            activo.kill_enviado = True

    def _finalizar(self, s: Session, trabajo: Trabajo, activo: _Activo, codigo: int) -> None:
        activo.lector.join(timeout=2)
        _senal(activo, signal.SIGKILL)  # por si el minijob dejó procesos hijos
        carpeta = carpeta_trabajo(self.zona, trabajo.id)
        trabajo.pid = None

        if trabajo.estado == Estado.CANCELANDOSE.value:
            cambiar_estado(s, trabajo, Estado.CANCELADO)
            borrar(carpeta)
            return
        if activo.por_tiempo:
            n = activo.minijob.tiempo_maximo_s
            cambiar_estado(s, trabajo, Estado.FALLIDO,
                           error_usuario=f"El trabajo superó el tiempo máximo ({n} s) y se detuvo.",
                           error_tecnico=f"Tiempo máximo de {n} s superado; código de salida {codigo}.")
            return
        if codigo == 0:
            informe = _leer_json(carpeta / INFORME)
            if informe is None:
                cambiar_estado(s, trabajo, Estado.FALLIDO,
                               error_usuario="El minijob terminó sin devolver un informe.",
                               error_tecnico=_cola_del_log(carpeta / LOG))
                return
            trabajo.informe = informe
            trabajo.progreso = 100
            destino = Estado.TERMINADO_CON_AVISOS if informe.get("fallos") else Estado.TERMINADO
            cambiar_estado(s, trabajo, destino)
            return
        error = _leer_json(carpeta / ERROR) or {}
        cambiar_estado(
            s, trabajo, Estado.FALLIDO,
            error_usuario=error.get("usuario") or f"El minijob terminó de forma inesperada (código {codigo}).",
            error_tecnico=error.get("tecnico") or _cola_del_log(carpeta / LOG) or f"Código de salida {codigo}.")

    # ---- arranque de trabajos pendientes ----
    def _cupo_libre(self, peso: str) -> bool:
        en_uso = sum(1 for a in self._activos.values() if a.minijob.peso == peso)
        return en_uso < self._maximos[peso]

    def _lanzar_pendientes(self) -> None:
        with self._sesiones() as s:
            pendientes = s.scalars(
                select(Trabajo).where(Trabajo.estado == Estado.PENDIENTE.value)
                .order_by(Trabajo.creado_en).with_for_update(skip_locked=True)).all()
            if not pendientes:
                return
            minijobs = {m.id: m for m in registro.descubrir()[0]}
            for trabajo in pendientes:
                minijob = minijobs.get(trabajo.minijob_id)
                if minijob is None:
                    cambiar_estado(s, trabajo, Estado.FALLIDO,
                                   error_usuario=f"El minijob «{trabajo.minijob_id}» no está instalado.")
                    continue
                if self._cupo_libre(minijob.peso):
                    self._arrancar(s, trabajo, minijob)
            s.commit()

    def _arrancar(self, s: Session, trabajo: Trabajo, minijob: Minijob) -> None:
        carpeta = carpeta_trabajo(self.zona, trabajo.id)
        preparar_ejecucion(carpeta, trabajo.entradas)
        entorno = os.environ.copy()
        entorno["PYTHONPATH"] = os.pathsep.join(
            [RAIZ_PAQUETE] + ([entorno["PYTHONPATH"]] if entorno.get("PYTHONPATH") else []))
        try:
            popen = subprocess.Popen(
                [sys.executable, "-m", "alfred.nucleo.trabajos.proceso", str(carpeta), str(minijob.ruta)],
                cwd=carpeta / "temporal", env=entorno, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                start_new_session=True)  # grupo propio: se puede cortar con todo lo que lance
        except OSError as e:
            cambiar_estado(s, trabajo, Estado.FALLIDO,
                           error_usuario="No se pudo lanzar el trabajo.", error_tecnico=repr(e))
            return
        try:
            cambiar_estado(s, trabajo, Estado.EN_CURSO)
            trabajo.pid = popen.pid
            registrar(s, "trabajo.lanzado", f"Proceso {popen.pid} lanzado para {minijob.id}",
                      detalle={"pid": popen.pid}, trabajo_id=trabajo.id)
            s.commit()
        except Exception:
            os.killpg(popen.pid, signal.SIGKILL)
            raise
        cola: queue.Queue = queue.Queue()
        lector = threading.Thread(target=_leer_salida, args=(popen.stdout, cola, carpeta / LOG),
                                  daemon=True)
        lector.start()
        self._activos[trabajo.id] = _Activo(popen, minijob, time.monotonic(), cola, lector)

    # ---- parada de Alfred ----
    def _interrumpir_activos(self) -> None:
        if not self._activos:
            return
        for activo in self._activos.values():
            _senal(activo, signal.SIGTERM)
        limite = time.monotonic() + self.gracia_s
        while time.monotonic() < limite and any(a.popen.poll() is None for a in self._activos.values()):
            time.sleep(0.05)
        for activo in self._activos.values():
            _senal(activo, signal.SIGKILL)
            activo.popen.wait()
        with self._sesiones() as s:
            for trabajo_id in list(self._activos):
                trabajo = s.get(Trabajo, trabajo_id, with_for_update=True)
                trabajo.pid = None
                cambiar_estado(s, trabajo, Estado.INTERRUMPIDO,
                               error_usuario="Alfred se detuvo mientras se ejecutaba el trabajo.")
                del self._activos[trabajo_id]
            s.commit()
