"""Hash de contraseñas con scrypt (biblioteca estándar, sin dependencias extra).

Formato: scrypt$<log2 N>$<r>$<p>$<sal b64>$<hash b64>. Lleva sus propios parámetros, así que se
puede endurecer en el futuro sin invalidar los hashes existentes.
"""
import base64
import hashlib
import hmac
import os

N_LOG2_DEFECTO = 15  # ~32 MiB y unas decenas de milisegundos por comprobación
N_LOG2 = N_LOG2_DEFECTO
R, P = 8, 1
MEMORIA_MAX = 128 * 1024 * 1024


def _b64(datos: bytes) -> str:
    return base64.b64encode(datos).decode()


def _scrypt(clave: str, sal: bytes, n_log2: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(clave.encode(), salt=sal, n=2 ** n_log2, r=r, p=p, maxmem=MEMORIA_MAX, dklen=32)


def hashear(clave: str) -> str:
    sal = os.urandom(16)
    return f"scrypt${N_LOG2}${R}${P}${_b64(sal)}${_b64(_scrypt(clave, sal, N_LOG2, R, P))}"


def verificar(clave: str, almacenado: str) -> bool:
    try:
        esquema, n_log2, r, p, sal, esperado = almacenado.split("$")
        if esquema != "scrypt":
            return False
        calculado = _scrypt(clave, base64.b64decode(sal), int(n_log2), int(r), int(p))
        return hmac.compare_digest(calculado, base64.b64decode(esperado))
    except (ValueError, TypeError):
        return False


_hash_falso: str | None = None


def verificar_falso(clave: str) -> None:
    """Gasta el mismo tiempo que una comprobación real (para no revelar si el usuario existe)."""
    global _hash_falso
    if _hash_falso is None:
        _hash_falso = hashear("clave que nunca se usa")
    verificar(clave, _hash_falso)
