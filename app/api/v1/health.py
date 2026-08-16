"""GET /v1/health — el "hola mundo" hito de la Semana 1.

GET /v1/health/ready — A.1.4 (Bloque A2, 2026-08-16): el healthcheck que de
verdad usa Railway (`railway.json::healthcheckPath`) tiene que tocar la base
de datos. `/v1/health` no la toca a propósito: sigue sirviendo para el
reinicio de plataforma, sin depender de Postgres.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.db import get_db

logger = logging.getLogger("api_legal")

router = APIRouter(tags=["health"])

# Corto a propósito: un `SELECT 1` sano tarda milisegundos, y este límite
# existe para que un Postgres colgado no deje la petición esperando hasta el
# `healthcheckTimeout` de Railway (60s, `railway.json`). Se fija con
# `SET LOCAL` dentro de la misma transacción en vez de en la creación del
# engine (`app/core/db.py`): así queda acotado a esta consulta y no cambia el
# comportamiento del resto de la aplicación.
TIMEOUT_SELECT_1_MS = 3000


@router.get("/health")
def health_check() -> dict:
    """Camino feliz: confirma que el servicio esta vivo."""
    return {
        "status": "ok",
        "service": "api-legal",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/health/ready")
def health_ready(response: Response, db: Session = Depends(get_db)) -> dict:
    """Confirma que el servicio puede hablar con Postgres, no solo que el
    proceso está vivo. Si la base no responde, devuelve 503 con un mensaje
    genérico: este endpoint es público, así que ni la excepción de SQLAlchemy
    ni nada de `DATABASE_URL` puede llegar al cuerpo de la respuesta — el
    detalle va solo al log (regla de T4)."""
    try:
        db.execute(text(f"SET LOCAL statement_timeout = {TIMEOUT_SELECT_1_MS}"))
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        logger.error("health_ready_fallo", extra={"tipo_error": type(error).__name__})
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "error", "db": "error"}

    return {"status": "ok", "db": "ok"}
