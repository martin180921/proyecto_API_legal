"""`app/core/rate_limit.py`: fuga de memoria de `_intentos` (A.3.8)."""
import time

from app.core import rate_limit


def test_vigentes_con_clave_nueva_no_crea_entrada_en_intentos():
    """`_vigentes` era la lectura que creaba el hueco: sobre un `defaultdict`,
    `_intentos[clave]` creaba la entrada por el solo hecho de leerla. Con
    `dict` normal y `.get(clave, [])`, una lectura pura no debe dejar rastro.

    Se prueba `_vigentes` directamente y no `limite_superado`/
    `registrar_intento`: esos dos ya escriben `_intentos[clave] = vigentes`
    de forma explícita después de leer, así que el estado final del
    diccionario tras llamarlos es el mismo con o sin `defaultdict` — la fuga
    que este cambio cierra es la de cualquier lectura que NO vaya seguida de
    esa escritura, hoy inexistente pero la que `defaultdict` dejaba abierta
    para el día que apareciera una."""
    resultado = rate_limit._vigentes("clave-nunca-vista", time.monotonic())

    assert resultado == []
    assert "clave-nunca-vista" not in rate_limit._intentos
