"""Rate-limit por contador simple en memoria (T4): login y registro.

Parámetro fijado por Martin el 2026-08-05 (Plan técnico por fases, bóveda):
5 intentos por clave en una ventana de 15 minutos, "contador simple (sin
slowapi)". Se implementa como un diccionario en el propio proceso porque
`railway.json` arranca un único proceso uvicorn sin `--workers`: mientras el
despliegue sea un solo proceso, este contador ve todos los intentos. Si el
piloto pasa a varios procesos o réplicas, deja de compartir estado entre
ellos y hace falta Redis o una tabla — no antes, sería sobre-ingeniería para
un bufete.
"""
import time
from collections import defaultdict
from threading import Lock

VENTANA_SEGUNDOS = 15 * 60
LIMITE_INTENTOS = 5

_intentos: dict[str, list[float]] = defaultdict(list)
_candado = Lock()


def _vigentes(clave: str, ahora: float) -> list[float]:
    return [marca for marca in _intentos[clave] if ahora - marca < VENTANA_SEGUNDOS]


def limite_superado(clave: str) -> bool:
    """True si `clave` ya acumuló 5 intentos fallidos en los últimos 15 minutos."""
    ahora = time.monotonic()
    with _candado:
        vigentes = _vigentes(clave, ahora)
        _intentos[clave] = vigentes
        return len(vigentes) >= LIMITE_INTENTOS


def registrar_intento(clave: str) -> int:
    """Anota un intento bajo `clave`. Devuelve cuántos quedan vigentes en la
    ventana, incluido este.

    Qué cuenta como «intento» lo decide quien llama, y no siempre es un fallo:
    en el login se cuentan los intentos fallidos, pero en `/registro` se cuenta
    **toda** petición, porque ahí lo que se está limitando es el trabajo caro
    (bcrypt) y la creación de organizaciones, no el error."""
    ahora = time.monotonic()
    with _candado:
        vigentes = _vigentes(clave, ahora)
        vigentes.append(ahora)
        _intentos[clave] = vigentes
        return len(vigentes)


def reiniciar() -> None:
    """Vacía el estado en memoria. Solo para pruebas: sin esto, los tests de
    rate-limit se contaminarían entre sí dentro de la misma sesión de pytest."""
    with _candado:
        _intentos.clear()
