"""`/v1/expedientes` — CRUD del expediente (Etapa Entrada, S3–4, Plan técnico
por fases).

Todo endpoint exige actor autenticado (`usuario_actual`) y toda consulta o
mutación filtra por `organizacion_id` del actor — mismo patrón que
`app/api/v1/auth.py` con `Usuario`. Un expediente de otra organización no es
visible ni editable: se responde 404, no 403 ni 401, para no revelar si el id
existe en otra organización ([[Multi-tenancy y audit log desde el día 1]]).

Paginación de `GET /v1/expedientes`: `limit`/`offset` (decidido con Martin,
2026-08-15, al no estar fijado en otro sitio de la bóveda) — `{items, total}`.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import ActorActual, usuario_actual, usuario_actual_verificado
from app.models.expediente import Expediente
from app.schemas.expediente import (
    ExpedienteActualizar,
    ExpedienteCrear,
    ExpedienteListaResponse,
    ExpedienteResponse,
)
from app.services import expedientes

router = APIRouter(prefix="/expedientes", tags=["expedientes"])

LIMITE_POR_DEFECTO = 20
LIMITE_MAXIMO = 100

_CONFLICTO_IDENTIFICADOR = "Ya existe un expediente con ese identificador en esta organización."


def _obtener_o_404(
    db: Session, organizacion_id: uuid.UUID, expediente_id: uuid.UUID
) -> Expediente:
    expediente = expedientes.obtener(db, organizacion_id, expediente_id)
    if expediente is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Expediente no encontrado"
        )
    return expediente


@router.post("", response_model=ExpedienteResponse, status_code=status.HTTP_201_CREATED)
def crear(
    payload: ExpedienteCrear,
    actor: ActorActual = Depends(usuario_actual_verificado),
    db: Session = Depends(get_db),
) -> Expediente:
    try:
        return expedientes.crear(db, actor.organizacion_id, actor.usuario_id, payload)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_CONFLICTO_IDENTIFICADOR)


@router.get("", response_model=ExpedienteListaResponse)
def listar(
    limit: int = Query(default=LIMITE_POR_DEFECTO, ge=1, le=LIMITE_MAXIMO),
    offset: int = Query(default=0, ge=0),
    actor: ActorActual = Depends(usuario_actual),
    db: Session = Depends(get_db),
) -> ExpedienteListaResponse:
    items, total = expedientes.listar(db, actor.organizacion_id, limit, offset)
    return ExpedienteListaResponse(items=items, total=total)


@router.get("/{expediente_id}", response_model=ExpedienteResponse)
def obtener(
    expediente_id: uuid.UUID,
    actor: ActorActual = Depends(usuario_actual),
    db: Session = Depends(get_db),
) -> Expediente:
    return _obtener_o_404(db, actor.organizacion_id, expediente_id)


@router.patch("/{expediente_id}", response_model=ExpedienteResponse)
def actualizar(
    expediente_id: uuid.UUID,
    payload: ExpedienteActualizar,
    actor: ActorActual = Depends(usuario_actual_verificado),
    db: Session = Depends(get_db),
) -> Expediente:
    expediente = _obtener_o_404(db, actor.organizacion_id, expediente_id)
    try:
        return expedientes.actualizar(
            db, actor.organizacion_id, actor.usuario_id, expediente, payload
        )
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_CONFLICTO_IDENTIFICADOR)


@router.post("/{expediente_id}/archivar", response_model=ExpedienteResponse)
def archivar(
    expediente_id: uuid.UUID,
    actor: ActorActual = Depends(usuario_actual_verificado),
    db: Session = Depends(get_db),
) -> Expediente:
    expediente = _obtener_o_404(db, actor.organizacion_id, expediente_id)
    return expedientes.archivar(db, actor.organizacion_id, actor.usuario_id, expediente)
