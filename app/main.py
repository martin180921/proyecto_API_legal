"""Punto de entrada de la API.

Rutas versionadas bajo /v1 desde el primer endpoint — Reglas de trabajo del
desarrollador único, regla 1: "contrato explícito".
"""
import logging
import time
import uuid

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exception_handlers import (
    http_exception_handler as _http_exception_handler_por_defecto,
)
from fastapi.exception_handlers import (
    request_validation_exception_handler as _validation_exception_handler_por_defecto,
)
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.auth import router as auth_router
from app.api.v1.estado_fuentes import router as estado_fuentes_router
from app.api.v1.expedientes import router as expedientes_router
from app.api.v1.health import router as health_router
from app.api.v1.usuarios import router as usuarios_router
from app.core.config import settings
from app.core.contexto import id_peticion_actual
from app.core.errores import ErrorDeDominio, codigo_por_status
from app.core.logging import configure_logging
from app.core.red import ip_cliente
from app.web.auth import NoAutenticadoWeb
from app.web.router import router as web_router

configure_logging()
logger = logging.getLogger("api_legal")

app = FastAPI(
    title="API Legal",
    description=(
        "Plataforma para usuarios individuales y firmas pequeñas del ambito "
        "legal, construida sobre una API disenada desde el dia 1 con el rigor "
        "de un producto publico."
    ),
    version="0.1.0",
)

# Métodos y cabeceras del CORS (C.2, Bloque C), en constantes propias para
# que `tests/test_cors.py` monte el mismo `CORSMiddleware` con estos valores
# exactos en vez de copiarlos a mano y arriesgarse a que diverjan.
CORS_METODOS = ["GET", "POST", "PATCH", "DELETE"]
CORS_CABECERAS = ["Authorization", "Content-Type", "X-CSRF-Token"]

# Lista blanca (C.2, Bloque C): `cors_origenes_lista` vacía por defecto = sin
# cabeceras CORS, el estado seguro. Nunca `allow_origins=["*"]` con
# `allow_credentials=True` — CORS lo prohíbe (la cookie de sesión de C.3 exige
# credentials), y los navegadores lo rechazan igual si se intenta.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origenes_lista,
    allow_credentials=True,
    allow_methods=CORS_METODOS,
    allow_headers=CORS_CABECERAS,
)

app.include_router(health_router, prefix=settings.api_v1_prefix)
app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.include_router(expedientes_router, prefix=settings.api_v1_prefix)
app.include_router(usuarios_router, prefix=settings.api_v1_prefix)
app.include_router(estado_fuentes_router, prefix=settings.api_v1_prefix)
app.include_router(web_router)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Logging estructurado de cada petición, con `request_id` para poder
    correlacionar esta línea con el evento de auditoría que la petición haya
    producido (A.3.3, Bloque A2, 2026-08-16).

    El `request_id` se fija en `id_peticion_actual` ANTES de `call_next`: es
    la única forma de que se propague al código que atiende la petición —ver
    `app/core/contexto.py`—, incluida `app/services/auditoria.py::registrar`,
    que lo añade a `detalle`.

    `xff` (la cabecera `X-Forwarded-For` cruda) e `ip_resuelta` (lo que
    devuelve `ip_cliente`) no son secretos y quedan de forma permanente: son
    el diagnóstico que hace falta para cerrar A.1.5 — si Railway reescribe la
    cabecera o la añade — sin depender de provocar un 429 de login primero.
    """
    request_id = str(uuid.uuid4())
    # También en `request.state`, que sobrevive más allá del `reset()` de más
    # abajo: `unhandled_exception_handler` corre en `ServerErrorMiddleware`,
    # FUERA de este middleware (Starlette pone el handler de `Exception` ahí,
    # no en `ExceptionMiddleware`), así que cuando lo alcanza una excepción no
    # controlada el contextvar ya se reseteó en el `finally` de abajo.
    request.state.request_id = request_id
    token = id_peticion_actual.set(request_id)
    inicio = time.monotonic()
    # try/finally (revisión P4, 2026-08-22): el handler global de Exception
    # corre por FUERA de este middleware, así que cuando `call_next` lanza,
    # sin esto la petición se quedaba sin línea de log, sin `X-Request-ID` y
    # sin `reset()` del contextvar — justo las peticiones que revientan, las
    # que más falta hace correlacionar. Si hubo excepción se loguea con
    # status_code=500 (lo que el handler global va a responder) y se relanza
    # para que ese handler siga construyendo la misma respuesta de siempre.
    response = None
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        id_peticion_actual.reset(token)
        duracion_ms = round((time.monotonic() - inicio) * 1000, 2)
        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code if response is not None else 500,
                "duracion_ms": duracion_ms,
                "xff": request.headers.get("x-forwarded-for"),
                "ip_resuelta": ip_cliente(request),
            },
        )


def _cuerpo_error(codigo: str, mensaje: str, detalle: list[dict] | None = None) -> dict:
    """El sobre único de error de `/v1` (C.1): `codigo` es lo que compara el
    frontend y los integradores, `request_id` correlaciona con la línea de
    log de `log_requests`."""
    return {
        "codigo": codigo,
        "mensaje": mensaje,
        "detalle": detalle,
        "request_id": id_peticion_actual.get(),
    }


@app.exception_handler(ErrorDeDominio)
async def error_de_dominio_handler(request: Request, exc: ErrorDeDominio) -> JSONResponse:
    cuerpo = _cuerpo_error(exc.codigo, exc.mensaje, exc.detalle)
    cuerpo["detail"] = exc.mensaje  # alias de compatibilidad durante F1 (C.1)
    return JSONResponse(status_code=exc.status_code, content=cuerpo)


@app.exception_handler(RequestValidationError)
async def validacion_handler(request: Request, exc: RequestValidationError):
    """422 de FastAPI/Pydantic con el mismo sobre que el resto de `/v1`
    (C.1). Fuera de `/v1` (`app/web`, `/docs`...) se conserva el formato por
    defecto: la validación ahí nunca formó parte del contrato público."""
    if not request.url.path.startswith(settings.api_v1_prefix):
        return await _validation_exception_handler_por_defecto(request, exc)
    detalle = [
        {"campo": ".".join(str(parte) for parte in error["loc"] if parte != "body"), "problema": error["msg"]}
        for error in exc.errors()
    ]
    cuerpo = _cuerpo_error("validacion", "Error de validación.", detalle)
    # `exc.errors()` puede traer `ctx.error` con la excepción original
    # (p. ej. el `ValueError` de un `model_validator`) — no serializable por
    # `json.dumps` directo, que es lo que usa `JSONResponse`. Mismo
    # tratamiento que el handler por defecto de FastAPI.
    cuerpo["detail"] = jsonable_encoder(exc.errors())  # alias de compatibilidad durante F1 (C.1)
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=cuerpo)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Traduce el `HTTPException` que el resto del código sigue lanzando a
    mano (auth, rate-limit, 404 de expedientes...) al mismo sobre (C.1).
    Fuera de `/v1` se conserva el comportamiento por defecto de
    FastAPI/Starlette: `app/web` resuelve su propio `HTTPException` antes de
    que llegue aquí (ver `procesar_login` en `app/web/router.py`) salvo
    `NoAutenticadoWeb`, que tiene su propio handler."""
    if not request.url.path.startswith(settings.api_v1_prefix):
        return await _http_exception_handler_por_defecto(request, exc)
    if isinstance(exc.detail, dict) and "codigo" in exc.detail:
        codigo = exc.detail["codigo"]
        mensaje = exc.detail.get("mensaje", "")
        detalle = exc.detail.get("detalle")
    else:
        codigo = codigo_por_status(exc.status_code)
        mensaje = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        detalle = None
    cuerpo = _cuerpo_error(codigo, mensaje, detalle)
    cuerpo["detail"] = exc.detail  # alias de compatibilidad durante F1 (C.1)
    return JSONResponse(status_code=exc.status_code, content=cuerpo, headers=exc.headers)


@app.exception_handler(NoAutenticadoWeb)
async def no_autenticado_web_handler(request: Request, exc: NoAutenticadoWeb) -> RedirectResponse:
    """Sin cookie de sesión válida en `app/web`: redirige a `/login` en vez
    del 401 JSON que usa la API — ver `app/web/auth.py`."""
    return RedirectResponse(url="/login", status_code=303)


_PAGINA_ERROR_WEB = """<!doctype html>
<html lang="es">
<head><meta charset="utf-8"><title>Error</title></head>
<body>
<h1>Ha ocurrido un error</h1>
<p>Algo ha salido mal al procesar tu solicitud. Vuelve a intentarlo en unos minutos.</p>
</body>
</html>
"""


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """JSON en `/v1` (contrato de la API); una página HTML mínima en el
    resto (`app/web`, montada sin prefijo): un error ahí no debe enseñarle
    JSON crudo al abogado. `/docs`, `/redoc` y `/openapi.json` no empiezan
    por `settings.api_v1_prefix` y caen del lado HTML — decisión tomada con
    Martin el 2026-08-20 (Bloque A4): un 500 ahí es rarísimo (son endpoints
    casi estáticos de FastAPI) y no vale la pena una segunda condición.

    La excepción real —mensaje, tipo, traceback— nunca sale de aquí: solo va
    al log, con el mismo criterio que ya seguía este handler antes de
    discriminar por superficie.
    """
    logger.error(
        "unhandled_exception",
        extra={"path": request.url.path, "error": str(exc)},
    )
    if request.url.path.startswith(settings.api_v1_prefix):
        cuerpo = _cuerpo_error("error_interno", "Error interno")
        # El contextvar ya se reseteó (ver el comentario en `log_requests`);
        # `request.state` es lo único que sobrevive hasta aquí.
        cuerpo["request_id"] = getattr(request.state, "request_id", None)
        cuerpo["detail"] = "Error interno"  # alias de compatibilidad durante F1 (C.1)
        return JSONResponse(status_code=500, content=cuerpo)
    return HTMLResponse(status_code=500, content=_PAGINA_ERROR_WEB)
