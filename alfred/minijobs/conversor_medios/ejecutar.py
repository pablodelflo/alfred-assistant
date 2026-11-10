"""Conversor de medios. Convierte todos los ficheros de la carpeta de entrada."""
import shutil
from pathlib import Path

from alfred.comun.contrato import Cancelado, Contexto, ErrorUsuario, Informe

from .catalogo import CATALOGO


def _numerar(destino: Path) -> Path:
    n = 1
    while True:
        candidato = destino.with_name(f"{destino.stem} ({n}){destino.suffix}")
        if not candidato.exists():
            return candidato
        n += 1


def ejecutar(ctx: Contexto) -> Informe:
    e = ctx.entradas
    conversion = CATALOGO.get(e.get("conversion"))
    if conversion is None:
        raise ErrorUsuario("La conversión pedida no existe.")
    opciones = {"calidad": int(e.get("calidad", 90)),
                "conservar_metadatos": bool(e.get("conservar_metadatos", True)),
                "quitar_gps": bool(e.get("quitar_gps", False)),
                "redimensionar": int(e.get("redimensionar", 0))}
    si_existe = e.get("si_existe", "numerar")

    ficheros = sorted(p for p in ctx.carpeta_entrada.rglob("*") if p.is_file())
    if not ficheros:
        raise ErrorUsuario("No hay ficheros que convertir.")

    resultados, fallos, omitidos = [], [], []
    total = len(ficheros)
    for i, origen in enumerate(ficheros, 1):
        ctx.comprobar_cancelacion()
        rel = origen.relative_to(ctx.carpeta_entrada)
        ctx.progreso((i - 1) * 100 // total, f"{rel} ({i} de {total})")

        if origen.suffix.lower() not in conversion.extensiones_entrada:
            omitidos.append({"elemento": str(rel), "motivo": "No es un tipo de fichero convertible"})
            continue
        destino = (ctx.carpeta_salida / rel).with_suffix(conversion.extension_salida)
        destino.parent.mkdir(parents=True, exist_ok=True)
        if destino.exists():
            if si_existe == "omitir":
                omitidos.append({"elemento": str(rel), "motivo": "Ya existía un fichero con ese nombre"})
                continue
            if si_existe == "numerar":
                destino = _numerar(destino)

        temporal = ctx.carpeta_temporal / f"{i}{conversion.extension_salida}"
        try:
            conversion.convertir(origen, temporal, opciones)
            shutil.move(str(temporal), destino)  # en la salida solo hay ficheros completos
            resultados.append({"entrada": str(rel), "salida": str(destino.relative_to(ctx.carpeta_salida)),
                               "bytes": destino.stat().st_size})
        except Cancelado:
            raise
        except Exception as error:  # un fichero corrupto no detiene el lote
            temporal.unlink(missing_ok=True)
            fallos.append({"elemento": str(rel),
                           "motivo": "No se pudo convertir (fichero dañado o no compatible)",
                           "detalle": f"{type(error).__name__}: {error}"[:500]})

    ctx.progreso(100, "Terminado")
    return Informe(resumen=f"{len(resultados)} convertidos, {len(omitidos)} omitidos, {len(fallos)} fallidos",
                   resultados=resultados, fallos=fallos, omitidos=omitidos)
