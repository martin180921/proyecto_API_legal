"""`/v1/usuarios` — lectura, para el selector de responsable del SPA (C.5,
Bloque C). Filtrado por `organizacion_id` del actor, mismo patrón que
`app/api/v1/expedientes.py`. Sin alta ni edición aquí: sigue siendo
`scripts/crear_organizacion.py` para el primer usuario; no hay endpoint de
alta de usuarios adicionales todavía.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import ActorActual, usuario_actual_verificado
from app.schemas.usuario import UsuarioListaResponse
from app.services import usuarios

router = APIRouter(prefix="/usuarios", tags=["usuarios"])


@router.get("", response_model=UsuarioListaResponse)
def listar(
    actor: ActorActual = Depends(usuario_actual_verificado),
    db: Session = Depends(get_db),
) -> UsuarioListaResponse:
    return UsuarioListaResponse(items=usuarios.listar(db, actor.organizacion_id))
