"""Punto de entrada de la API.

Rutas versionadas bajo /v1 desde el primer endpoint — Reglas de trabajo del
desarrollador único, regla 1: "contrato explícito".
"""
import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.v1.auth import router as auth_router
from app.api.v1.expedientes import router as expedientes_router
from app.api.v1.health import router as health_router
from app.core.config import settings
from app.core.contexto import id_peticion_actual
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

app.include_router(health_router, prefix=settings.api_v1_prefix)
app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.include_router(expedientes_router, prefix=settings.api_v1_prefix)
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
    token = id_peticion_actual.set(request_id)
    inicio = time.monotonic()
    response = await call_next(request)
    id_peticion_actual.reset(token)
    duracion_ms = round((time.monotonic() - inicio) * 1000, 2)

    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duracion_ms": duracion_ms,
            "xff": request.headers.get("x-forwarded-for"),
            "ip_resuelta": ip_cliente(request),
        },
    )
    return response


@app.exception_handler(NoAutenticadoWeb)
async def no_autenticado_web_handler(request: Request, exc: NoAutenticadoWeb) -> RedirectResponse:
    """Sin cookie de sesión válida en `app/web`: redirige a `/login` en vez
    del 401 JSON que usa la API — ver `app/web/auth.py`."""
    return RedirectResponse(url="/login", status_code=303)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(
        "unhandled_exception",
        extra={"path": request.url.path, "error": str(exc)},
    )
    return JSONResponse(status_code=500, content={"detail": "Error interno"})
