"""Punto de entrada de la API.

Rutas versionadas bajo /v1 desde el primer endpoint — Reglas de trabajo del
desarrollador único, regla 1: "contrato explícito".
"""
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.v1.auth import router as auth_router
from app.api.v1.expedientes import router as expedientes_router
from app.api.v1.health import router as health_router
from app.core.config import settings
from app.core.logging import configure_logging
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
    """Logging estructurado de cada peticion — tarea de la Semana 1."""
    response = await call_next(request)
    logger.info(
        "request",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
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
