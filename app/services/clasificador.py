"""Clasificador de actuaciones (Etapa Procesamiento, regla 5 de Juan Diego):
por reglas y palabras clave, sin IA. El hueco para clasificar con IA se deja
para F2, cuando haya casos reales con los que medirla.

Función pura de `(tipo, anotación)`: no toca la base de datos ni guarda nada.
La clasificación no se persiste en `actuaciones` a propósito — así un cambio
de reglas no deja filas viejas con la etiqueta anterior ni exige migración.
Quien la necesite (alertas, `terminos.py`, la API) la calcula al leer.

Cómo decide:

- Mira primero el `tipo` (el campo `actuacion` de la fuente), con las reglas en
  orden de especificidad: «inadmite» antes de «admite», «fijación en lista»
  antes de «fijación estado», y las categorías de contenido antes del `auto`
  genérico.
- Solo si el `tipo` es un `auto` genérico, la sustancia vive en la anotación
  («Auto — ordena correr traslado»), y entonces se mira ahí. Con cualquier
  otro `tipo` la anotación **no** se consulta: «Recepción memorial» con una
  anotación que dice «solicita audiencia» es un memorial, no una audiencia.
- Lo que no encaja es `OTRO`, nunca una categoría adivinada.
"""
from __future__ import annotations

import enum
import re
import unicodedata


class TipoActuacion(str, enum.Enum):
    AUTO = "auto"
    SENTENCIA = "sentencia"
    TRASLADO = "traslado"
    REQUERIMIENTO = "requerimiento"
    ESTADO = "estado"
    FIJACION_EN_LISTA = "fijacion_en_lista"
    AUDIENCIA = "audiencia"
    MANDAMIENTO_DE_PAGO = "mandamiento_de_pago"
    ADMISION = "admision"
    INADMISION = "inadmision"
    ARCHIVO = "archivo"
    OTRO = "otro"


# Orden = prioridad. Los patrones corren sobre texto sin tildes y en minúsculas.
_REGLAS: tuple[tuple[TipoActuacion, re.Pattern[str]], ...] = (
    (TipoActuacion.MANDAMIENTO_DE_PAGO, re.compile(r"\bmandamiento\b")),
    (TipoActuacion.INADMISION, re.compile(r"\binadmi")),
    (TipoActuacion.ADMISION, re.compile(r"\badmit|\badmis|\badmite")),
    (TipoActuacion.SENTENCIA, re.compile(r"\bsentencia")),
    (TipoActuacion.AUDIENCIA, re.compile(r"\baudiencia")),
    (TipoActuacion.ARCHIVO, re.compile(r"\barchiv")),
    (TipoActuacion.FIJACION_EN_LISTA, re.compile(r"\bfijacion\b.*\blista\b|\ben lista\b")),
    (TipoActuacion.ESTADO, re.compile(r"\bestados?\b")),
    (TipoActuacion.TRASLADO, re.compile(r"\btraslado")),
    (TipoActuacion.REQUERIMIENTO, re.compile(r"\brequerimiento|\brequier|\brequerir")),
)
_AUTO = re.compile(r"\bautos?\b")


def normalizar(texto: str | None) -> str:
    """Minúsculas, sin tildes ni diacríticos."""
    texto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in texto if not unicodedata.combining(c)).casefold()


def _buscar(texto: str) -> TipoActuacion | None:
    for tipo, patron in _REGLAS:
        if patron.search(texto):
            return tipo
    return None


def clasificar(tipo: str, anotacion: str | None = None) -> TipoActuacion:
    texto = normalizar(tipo)
    encontrado = _buscar(texto)
    if encontrado is not None:
        return encontrado
    if _AUTO.search(texto):
        return _buscar(normalizar(anotacion)) or TipoActuacion.AUTO
    return TipoActuacion.OTRO
