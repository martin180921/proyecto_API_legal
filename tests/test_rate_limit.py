"""`app/core/rate_limit.py`: fuga de memoria de `_intentos` (A.3.8)."""
import time

from app.core import rate_limit


def test_vigentes_con_clave_nueva_no_crea_entrada_en_intentos():
    """`_vigentes` era la lectura que creaba el hueco: sobre un `defaultdict`,
    `_intentos[clave]` creaba la entrada por el solo hecho de leerla. Con
    `dict` normal y `.get(clave, [])`, una lectura pura no debe dejar rastro.

    Se prueba `_vigentes` directamente porque es la primitiva de lectura; la
    prueba de abajo cubre el camino público (`limite_superado`), que era el
    que seguía escribiendo la entrada de forma incondicional."""
    resultado = rate_limit._vigentes("clave-nunca-vista", time.monotonic())

    assert resultado == []
    assert "clave-nunca-vista" not in rate_limit._intentos


def test_limite_superado_con_clave_nunca_vista_no_deja_entrada_en_intentos():
    """La regresión exacta que se coló en A.3.8 (revisión P4, 2026-08-22):
    `limite_superado` hacía `_intentos[clave] = vigentes` incondicionalmente,
    así que toda clave consultada —cada email probado, cada IP nueva— creaba
    una entrada permanente con lista vacía. Consultar no debe dejar rastro."""
    assert rate_limit.limite_superado("clave-nunca-vista") is False

    assert "clave-nunca-vista" not in rate_limit._intentos


def test_limite_superado_purga_la_entrada_cuando_todos_los_intentos_caducan(monkeypatch):
    """Complemento del anterior: una clave que sí tuvo intentos vuelve a
    desaparecer del diccionario cuando la ventana los caduca todos."""
    rate_limit.registrar_intento("clave-que-caduca")
    assert "clave-que-caduca" in rate_limit._intentos

    despues_de_la_ventana = time.monotonic() + rate_limit.VENTANA_SEGUNDOS + 1
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: despues_de_la_ventana)

    assert rate_limit.limite_superado("clave-que-caduca") is False
    assert "clave-que-caduca" not in rate_limit._intentos
