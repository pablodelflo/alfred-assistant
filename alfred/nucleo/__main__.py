"""Arranque del servidor: python -m alfred.nucleo"""
import sys

# Primero la versión de Python, con solo la biblioteca estándar: en versiones
# antiguas el resto del código ni siquiera se puede importar.
if sys.version_info < (3, 13):
    sys.exit(
        f"Alfred requiere Python 3.13 o superior; detectado "
        f"{sys.version_info.major}.{sys.version_info.minor}.\n"
        "Crea el entorno virtual con un Python 3.13 (ver README) y actívalo."
    )


def main() -> int:
    from alfred.nucleo.arranque.requisitos import comprobar_todo

    ok, config, resultados = comprobar_todo()
    for r in resultados:
        print(("[ok]    " if r.ok else "[FALLO] ") + r.mensaje)
    if not ok:
        print("\nNo se puede arrancar: corrige los fallos de arriba.")
        return 1

    import uvicorn
    from alfred.comun.version import VERSION
    from alfred.nucleo.actividad.registro import registrar
    from alfred.nucleo.datos.base import crear_motor, crear_sesiones
    from alfred.nucleo.trabajos.lanzador import Lanzador
    from alfred.nucleo.trabajos.recuperacion import recuperar
    from alfred.nucleo.web.app import crear_app

    sesiones = crear_sesiones(crear_motor(config.url_bd))
    interrumpidos = recuperar(sesiones)
    if interrumpidos:
        print(f"[aviso] {interrumpidos} trabajo(s) marcados como interrumpidos por el reinicio")
    with sesiones() as sesion:
        registrar(sesion, "sistema.arranque", f"Alfred {VERSION} arrancado")
        sesion.commit()
    lanzador = Lanzador(sesiones, config.zona_temporal.resolve(),
                        max_ligeros=config.max_ligeros, max_pesados=config.max_pesados,
                        gracia_cancelacion_s=config.gracia_cancelacion_s)

    uvicorn.run(crear_app(lanzador), host=config.host, port=config.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
