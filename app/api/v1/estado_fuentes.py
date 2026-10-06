"""`GET /v1/estado-fuentes` — última corrida del motor de revisión y qué
expedientes quedaron `no_verificado` y por qué (Etapa Procesamiento, P6).

Mismo patrón que el resto de `/v1`: actor verificado, todo filtrado por
`organizacion_id`, errores con el sobre de C.1 (401 `no_autenticado`, 422
`validacion`). Solo lectura.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import ActorActual, usuario_actual_verificado
from app.schemas.estado_fuentes import EstadoFuentesResponse
from app.services import estado_fuentes

router = APIRouter(prefix="/estado-fuentes", tags=["estado-fuentes"])

LIMITE_POR_DEFECTO = 50
LIMITE_MAXIMO = 100


@router.get("", response_model=EstadoFuentesResponse, operation_id="obtener_estado_fuentes")
def obtener(
    limit: int = Query(default=LIMITE_POR_DEFECTO, ge=1, le=LIMITE_MAXIMO),
    offset: int = Query(default=0, ge=0),
    actor: ActorActual = Depends(usuario_actual_verificado),
    db: Session = Depends(get_db),
) -> EstadoFuentesResponse:
    return estado_fuentes.obtener(db, actor.organizacion_id, limit, offset)
