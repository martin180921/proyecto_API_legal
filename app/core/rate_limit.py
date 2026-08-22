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
from threading import Lock

VENTANA_SEGUNDOS = 15 * 60
LIMITE_INTENTOS = 5

# La clave global por IP no hace el mismo trabajo que las por-organización y
# por eso no lleva el mismo número. Las de organización defienden una cuenta
# concreta de la fuerza bruta (5). Esta es un tope de enumeración: existe para
# que nadie barra slugs indefinidamente por el camino que no consumía contador.
# Con 5 se disparaba antes que las de organización —que se incrementan en el
# mismo fallo— y las dejaba inalcanzables, además de bloquear entre
# organizaciones a todo un despacho que comparte IP pública. Decidido por
# Martin el 2026-08-16 (Bloque A1 bis).
LIMITE_INTENTOS_IP_GLOBAL = 20

_intentos: dict[str, list[float]] = {}

# Claves cuyo cruce del umbral ya se auditó en la ventana actual. Se guarda el
# instante de la marca para poder caducarla con el mismo criterio que el
# contador: pasada la ventana, la clave vuelve a poder auditarse.
_auditadas: dict[str, float] = {}

_candado = Lock()


def _vigentes(clave: str, ahora: float) -> list[float]:
    """`.get(clave, [])`, no `_intentos[clave]`: con un `dict` normal (ya no
    `defaultdict`), leer una clave ausente no debe crearla. Antes sí la creaba
    — toda clave vista alguna vez (cada IP, cada email probado) dejaba un
    hueco permanente en el diccionario, incluso caducada la ventana (A.3.8).
    """
    return [marca for marca in _intentos.get(clave, []) if ahora - marca < VENTANA_SEGUNDOS]


def limite_superado(clave: str, limite: int = LIMITE_INTENTOS) -> bool:
    """True si `clave` ya acumuló `limite` intentos fallidos en los últimos 15
    minutos. Por defecto, los 5 de siempre; `LIMITE_INTENTOS_IP_GLOBAL` es el
    único llamador que pasa otro valor."""
    ahora = time.monotonic()
    with _candado:
        vigentes = _vigentes(clave, ahora)
        # Solo se escribe si hay algo que recordar: la asignación
        # incondicional de antes creaba una entrada permanente (con lista
        # vacía) por cada clave consultada — cada email probado, cada IP
        # nueva —, justo la fuga que A.3.8 decía haber cerrado.
        if vigentes:
            _intentos[clave] = vigentes
        else:
            _intentos.pop(clave, None)
        return len(vigentes) >= limite


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


def marcar_auditado(clave: str) -> bool:
    """True solo la **primera** vez que `clave` cruza el umbral en la ventana.

    Existe para que el rate-limit deje de amplificar lo que pretende frenar.
    Antes, cada petición bloqueada escribía una fila en `eventos_auditoria`:
    quien insistiera generaba escrituras ilimitadas en la única tabla que por
    diseño no se puede borrar. El rate-limit no detenía la escritura, la
    provocaba.

    Lo interesante para auditar es la **transición** —esta clave se ha
    bloqueado—, no cada una de las peticiones que rebotan después.
    """
    ahora = time.monotonic()
    with _candado:
        marca = _auditadas.get(clave)
        if marca is not None and ahora - marca < VENTANA_SEGUNDOS:
            return False
        # Una marca caducada no necesita purga aparte: la asignación de abajo
        # la sobrescribe siempre que se consulta. A diferencia de
        # `limite_superado`, aquí ninguna rama deja una entrada vacía.
        _auditadas[clave] = ahora
        return True


def limpiar(clave: str) -> None:
    """Olvida los intentos de `clave` y su marca de auditoría.

    La llama el login al autenticar correctamente. Sin esto, cuatro fallos y un
    acierto dejaban al usuario a un solo fallo del bloqueo durante el resto de
    la ventana — un acierto no contaba para nada. Comportamiento estándar.

    Se borra también la marca de `marcar_auditado`: si la clave vuelve a
    bloquearse después, ese bloqueo es una transición nueva y merece su evento.
    """
    with _candado:
        _intentos.pop(clave, None)
        _auditadas.pop(clave, None)


def reiniciar() -> None:
    """Vacía el estado en memoria. Solo para pruebas: sin esto, los tests de
    rate-limit se contaminarían entre sí dentro de la misma sesión de pytest."""
    with _candado:
        _intentos.clear()
        _auditadas.clear()
