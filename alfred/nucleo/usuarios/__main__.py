"""Gestión del administrador desde la terminal del servidor:

    python -m alfred.nucleo.usuarios crear [NOMBRE]          (por defecto «admin»)
    python -m alfred.nucleo.usuarios cambiar-clave [NOMBRE]  (cierra sus sesiones)
    python -m alfred.nucleo.usuarios cerrar-sesiones         (de todos)
    python -m alfred.nucleo.usuarios listar

La contraseña se pide por teclado (no queda en el historial de la terminal).
"""
import getpass
import sys


def _pedir_clave() -> str:
    clave = getpass.getpass("Contraseña (mínimo 12 caracteres): ")
    if clave != getpass.getpass("Repite la contraseña: "):
        raise SystemExit("Las contraseñas no coinciden.")
    return clave


def main(argv: list[str]) -> int:
    from sqlalchemy import select

    from alfred.nucleo.config.lectura import cargar
    from alfred.nucleo.datos.base import crear_motor, crear_sesiones
    from alfred.nucleo.datos.modelos import Usuario
    from alfred.nucleo.usuarios import servicio

    if not argv or argv[0] not in ("crear", "cambiar-clave", "cerrar-sesiones", "listar"):
        print(__doc__)
        return 2
    orden, nombre = argv[0], (argv[1] if len(argv) > 1 else "admin")
    sesiones = crear_sesiones(crear_motor(cargar().url_bd))
    try:
        with sesiones() as s:
            if orden == "listar":
                for u in s.scalars(select(Usuario).order_by(Usuario.id)):
                    print(f"{u.nombre}  creado {u.creado_en:%d/%m/%Y %H:%M}  último acceso {u.ultimo_acceso or '—'}")
                return 0
            if orden == "cerrar-sesiones":
                print(f"{servicio.cerrar_todas(s)} sesión(es) cerradas.")
            elif orden == "crear":
                servicio.crear_usuario(s, nombre, _pedir_clave())
                print(f"Administrador «{nombre.lower()}» creado.")
            else:
                cerradas = servicio.cambiar_clave(s, nombre, _pedir_clave())
                print(f"Contraseña cambiada; {cerradas} sesión(es) cerradas.")
            s.commit()
    except servicio.ErrorUsuario as e:
        print(e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
