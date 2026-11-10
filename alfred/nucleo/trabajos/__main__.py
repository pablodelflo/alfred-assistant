"""Gestión de trabajos desde la terminal (mientras no haya pantalla):

    python -m alfred.nucleo.trabajos crear MINIJOB [ENTRADAS_JSON]
    python -m alfred.nucleo.trabajos listar
    python -m alfred.nucleo.trabajos ver ID
    python -m alfred.nucleo.trabajos cancelar ID
    python -m alfred.nucleo.trabajos reintentar ID

Los trabajos los ejecuta el lanzador de Alfred, que debe estar arrancado.
ID puede ser el prefijo único que muestra `listar`.
"""
import json
import sys

USO = __doc__


def _buscar(sesion, prefijo: str):
    from sqlalchemy import select
    from alfred.nucleo.datos.modelos import Trabajo
    todos = sesion.scalars(select(Trabajo).order_by(Trabajo.creado_en)).all()
    coinciden = [t for t in todos if str(t.id).startswith(prefijo)]
    if len(coinciden) != 1:
        raise SystemExit(f"«{prefijo}» no identifica un único trabajo ({len(coinciden)} coincidencias).")
    return coinciden[0]


def main(argv: list[str]) -> int:
    from sqlalchemy import select
    from alfred.nucleo.config.lectura import cargar
    from alfred.nucleo.datos.base import crear_motor, crear_sesiones
    from alfred.nucleo.datos.modelos import Trabajo
    from alfred.nucleo.minijobs.registro import descubrir
    from alfred.nucleo.trabajos.servicio import (TransicionInvalida, crear_trabajo, reintentar,
                                                 solicitar_cancelacion)

    if not argv or argv[0] not in ("crear", "listar", "ver", "cancelar", "reintentar"):
        print(USO)
        return 2
    orden, args = argv[0], argv[1:]
    config = cargar()
    sesiones = crear_sesiones(crear_motor(config.url_bd))

    with sesiones() as s:
        if orden == "crear":
            if not args:
                print(USO)
                return 2
            if args[0] not in {m.id for m in descubrir()[0]}:
                print(f"El minijob «{args[0]}» no existe o no es válido.")
                return 1
            entradas = json.loads(args[1]) if len(args) > 1 else {}
            trabajo = crear_trabajo(s, args[0], entradas)
            s.commit()
            print(f"Trabajo creado: {str(trabajo.id)[:8]}  (completo: {trabajo.id})")
        elif orden == "listar":
            for t in reversed(s.scalars(select(Trabajo).order_by(Trabajo.creado_en.desc()).limit(20)).all()):
                print(f"{str(t.id)[:8]}  {t.estado:<21} {t.progreso:>3}%  {t.minijob_id}  {t.mensaje_progreso or ''}")
        else:
            if not args:
                print(USO)
                return 2
            t = _buscar(s, args[0])
            if orden == "ver":
                for campo in ("id", "minijob_id", "estado", "progreso", "mensaje_progreso", "pid",
                              "creado_en", "iniciado_en", "terminado_en", "entradas", "informe",
                              "error_usuario", "error_tecnico"):
                    print(f"{campo}: {getattr(t, campo)}")
            else:
                try:
                    if orden == "cancelar":
                        solicitar_cancelacion(s, t, config.zona_temporal.resolve())
                    else:
                        reintentar(s, t)
                except TransicionInvalida as e:
                    print(f"No se puede: {e}")
                    return 1
                s.commit()
                print(f"{orden.capitalize()}: {str(t.id)[:8]} -> {t.estado}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
