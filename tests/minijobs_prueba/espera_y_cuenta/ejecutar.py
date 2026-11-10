"""Minijob de prueba. Entradas (todas opcionales):

pasos (5), segundos_por_paso (1), fallos_parciales (0),
fallar ("usuario" | "inesperado": falla en el paso 2),
ignorar_cancelacion (false: no mira la cancelación, hay que cortarlo).
"""
import time

from alfred.comun.contrato import Contexto, ErrorUsuario, Informe


def ejecutar(ctx: Contexto) -> Informe:
    e = ctx.entradas
    pasos = int(e.get("pasos", 5))
    espera = float(e.get("segundos_por_paso", 1))
    fallos_parciales = int(e.get("fallos_parciales", 0))
    fallar = e.get("fallar")
    ignorar = bool(e.get("ignorar_cancelacion", False))

    (ctx.carpeta_temporal / "marca.txt").write_text("trabajando")
    resultados, fallos = [], []
    for i in range(1, pasos + 1):
        if not ignorar:
            ctx.comprobar_cancelacion()
        time.sleep(espera)
        ctx.progreso(i * 100 // pasos, f"Paso {i} de {pasos}")
        if fallar == "usuario" and i == 2:
            raise ErrorUsuario("Fichero de prueba dañado")
        if fallar == "inesperado" and i == 2:
            raise RuntimeError("Fallo inesperado de prueba")
        if i <= fallos_parciales:
            fallos.append({"elemento": f"paso {i}", "motivo": "fallo simulado"})
        else:
            resultados.append({"elemento": f"paso {i}"})

    (ctx.carpeta_salida / "resultado.txt").write_text(f"{pasos} pasos\n")
    return Informe(resumen=f"{len(resultados)} pasos correctos, {len(fallos)} fallidos",
                   resultados=resultados, fallos=fallos)
