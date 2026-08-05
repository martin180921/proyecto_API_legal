"""GET /v1/health — el "hola mundo" hito de la Semana 1."""
from datetime import datetime, timezone

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict:
    """Camino feliz: confirma que el servicio esta vivo."""
    return {
        "status": "ok",
        "service": "api-legal",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
