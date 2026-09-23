"""Errores de dominio con código estable — el contrato único de error para
`/v1` (Bloque C, C.1). Ver `app/main.py`, que registra el handler de
`ErrorDeDominio` junto con los de `RequestValidationError`, `HTTPException`
y `Exception` para que los cuatro devuelvan el mismo sobre JSON.
"""


class ErrorDeDominio(Exception):
    """Base de los errores que la API sabe explicar. `codigo` es contrato
    público: el frontend y los integradores comparan contra él, así que un
    código publicado NO se renombra — el `mensaje` sí puede cambiar.

    `detalle`, si se da, es una lista de `{"campo": ..., "problema": ...}` —
    el mismo shape que usa el handler de validación de Pydantic.
    """

    status_code: int = 400
    codigo: str = "error"
    mensaje: str = "Error de dominio."

    def __init__(self, mensaje: str | None = None, detalle: list[dict] | None = None):
        if mensaje is not None:
            self.mensaje = mensaje
        self.detalle = detalle
        super().__init__(self.mensaje)


# El resto del código sigue lanzando `HTTPException` a mano (auth, rate-limit,
# el 404 genérico de expedientes...) — no se migra de golpe a `ErrorDeDominio`
# en este paso, que solo toca `app/main.py`. Se traduce por `status_code` en
# un único sitio: si `detail` ya es un dict con "codigo" (el patrón que sigue
# `responsable_invalido` desde A5.3), se respeta tal cual; si es texto, se le
# asigna el código genérico de su `status_code`.
CODIGO_POR_STATUS: dict[int, str] = {
    400: "solicitud_invalida",
    401: "no_autenticado",
    403: "prohibido",
    404: "no_encontrado",
    409: "conflicto",
    422: "validacion",
    429: "limite_excedido",
    500: "error_interno",
}

CODIGO_POR_DEFECTO = "error"


def codigo_por_status(status_code: int) -> str:
    return CODIGO_POR_STATUS.get(status_code, CODIGO_POR_DEFECTO)
