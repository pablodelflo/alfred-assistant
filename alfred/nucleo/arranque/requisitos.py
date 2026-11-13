"""Comprobación de requisitos al arrancar."""
import importlib.util
import sys
from dataclasses import dataclass

from alfred.nucleo.config.lectura import Config, ErrorConfig, cargar

PYTHON_MINIMO = (3, 13)
# La 14 dejó de recibir correcciones el 12/11/2026. Mínimo: 16; recomendada: 18.
POSTGRES_MINIMO = 16


@dataclass
class Resultado:
    ok: bool
    mensaje: str


def comprobar_python() -> Resultado:
    v = sys.version_info
    if (v.major, v.minor) < PYTHON_MINIMO:
        return Resultado(False, f"Python {v.major}.{v.minor} detectado; se requiere {PYTHON_MINIMO[0]}.{PYTHON_MINIMO[1]} o superior.")
    return Resultado(True, f"Python {v.major}.{v.minor}.{v.micro}")


DEPENDENCIAS = ("fastapi", "uvicorn", "jinja2", "psycopg", "sqlalchemy", "alembic", "python_multipart")


def comprobar_dependencias() -> Resultado:
    faltan = [d for d in DEPENDENCIAS if importlib.util.find_spec(d) is None]
    if faltan:
        return Resultado(False, f"Faltan dependencias de Python: {', '.join(faltan)}. "
                                "Con el entorno virtual activado, ejecuta: pip install -e .")
    return Resultado(True, "Dependencias de Python instaladas")


def comprobar_postgres(config: Config) -> Resultado:
    try:
        import psycopg
    except ImportError:
        return Resultado(False, "Falta psycopg. Ejecuta: pip install -e .")
    try:
        with psycopg.connect(config.url_bd, connect_timeout=5) as con:
            version = con.info.server_version // 10000
    except Exception as e:
        return Resultado(False, f"No se pudo conectar a PostgreSQL ({type(e).__name__}). Revisa base_datos.url en la configuración.")
    if version < POSTGRES_MINIMO:
        return Resultado(False, f"PostgreSQL {version} detectado; se requiere {POSTGRES_MINIMO} o superior "
                                f"(se recomienda la 18).")
    return Resultado(True, f"PostgreSQL {version}")


def comprobar_esquema(config: Config) -> Resultado:
    from alfred.nucleo.datos.base import crear_motor
    from alfred.nucleo.datos.esquema import revision_actual, revision_cabeza

    try:
        actual = revision_actual(crear_motor(config.url_bd))
    except Exception as e:
        return Resultado(False, f"No se pudo leer el esquema de la base de datos ({type(e).__name__}).")
    if actual != revision_cabeza():
        return Resultado(False, "El esquema de la base de datos no está al día. "
                                "Ejecuta: python -m alfred.nucleo.datos actualizar")
    return Resultado(True, f"Esquema de base de datos al día (revisión {actual})")


def comprobar_zona_temporal(config: Config) -> Resultado:
    try:
        config.zona_temporal.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return Resultado(False, f"No se puede crear la zona temporal {config.zona_temporal}: {e}")
    return Resultado(True, f"Zona temporal: {config.zona_temporal}")


def comprobar_todo() -> tuple[bool, Config | None, list[Resultado]]:
    resultados = [comprobar_python(), comprobar_dependencias()]
    if not all(r.ok for r in resultados):
        return False, None, resultados
    try:
        config = cargar()
    except ErrorConfig as e:
        resultados.append(Resultado(False, str(e)))
        return False, None, resultados
    resultados.append(Resultado(True, "Configuración cargada"))
    resultados.append(comprobar_postgres(config))
    if resultados[-1].ok:
        resultados.append(comprobar_esquema(config))
    resultados.append(comprobar_zona_temporal(config))
    return all(r.ok for r in resultados), config, resultados
