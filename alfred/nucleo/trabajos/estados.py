"""Ciclo de vida de un trabajo: estados y transiciones permitidas.

Solo el núcleo cambia estados (ver servicio.cambiar_estado).
"""
from enum import StrEnum


class Estado(StrEnum):
    PENDIENTE = "pendiente"
    EN_CURSO = "en_curso"
    CANCELANDOSE = "cancelandose"
    TERMINADO = "terminado"
    TERMINADO_CON_AVISOS = "terminado_con_avisos"
    FALLIDO = "fallido"
    INTERRUMPIDO = "interrumpido"
    CANCELADO = "cancelado"


E = Estado

TRANSICIONES: dict[Estado, frozenset[Estado]] = {
    # Puede cancelarse antes de empezar, o fallar si no se logra lanzar.
    E.PENDIENTE: frozenset({E.EN_CURSO, E.CANCELADO, E.FALLIDO}),
    E.EN_CURSO: frozenset({E.TERMINADO, E.TERMINADO_CON_AVISOS, E.FALLIDO,
                           E.INTERRUMPIDO, E.CANCELANDOSE}),
    # Si termina "por su cuenta" mientras se cancela, el núcleo lo da por cancelado.
    E.CANCELANDOSE: frozenset({E.CANCELADO, E.FALLIDO, E.INTERRUMPIDO}),
    # Tras un reinicio se puede reintentar.
    E.INTERRUMPIDO: frozenset({E.PENDIENTE}),
    E.TERMINADO: frozenset(),
    E.TERMINADO_CON_AVISOS: frozenset(),
    E.FALLIDO: frozenset(),
    E.CANCELADO: frozenset(),
}

FINALES = frozenset(e for e, destinos in TRANSICIONES.items() if not destinos)


def es_final(estado: Estado) -> bool:
    return estado in FINALES


def transicion_valida(origen: Estado, destino: Estado) -> bool:
    return destino in TRANSICIONES[origen]


ETIQUETAS: dict[str, str] = {
    E.PENDIENTE.value: "Pendiente",
    E.EN_CURSO.value: "En curso",
    E.CANCELANDOSE.value: "Cancelándose",
    E.TERMINADO.value: "Terminado",
    E.TERMINADO_CON_AVISOS.value: "Terminado con avisos",
    E.FALLIDO.value: "Fallido",
    E.INTERRUMPIDO.value: "Interrumpido",
    E.CANCELADO.value: "Cancelado",
}

# Estados en los que el trabajo aún está vivo (la pantalla se refresca sola mientras haya alguno).
ACTIVOS = frozenset({E.PENDIENTE.value, E.EN_CURSO.value, E.CANCELANDOSE.value})
