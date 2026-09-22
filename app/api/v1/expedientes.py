"""`/v1/expedientes` — CRUD del expediente (Etapa Entrada, S3–4, Plan técnico
por fases).

Todo endpoint exige actor autenticado y toda consulta o mutación filtra por
`organizacion_id` del actor — mismo patrón que `app/api/v1/auth.py` con
`Usuario`. Un expediente de otra organización no es visible ni editable: se
responde 404, no 403 ni 401, para no revelar si el id existe en otra
organización ([[Multi-tenancy y audit log desde el día 1]]).

Todas las rutas —lectura y mutación— usan `usuario_actual_verificado`
(decisión de Martin, A5.1, 2026-09-22): un `SELECT` por PK de más en cada
lectura, para que desactivar a alguien le corte el acceso de inmediato en vez
de hasta que expire su JWT (hasta 8h).

Paginación de `GET /v1/expedientes`: `limit`/`offset` (decidido con Martin,
2026-08-15, al no estar fijado en otro sitio de la bóveda) — `{items, total}`.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import ActorActual, usuario_actual_verificado
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

# El mismo texto que da el validador Pydantic (`_validar_identificador` en
# app/schemas/expediente.py): el cliente ve el mismo error tanto si lo atrapa
# Pydantic (POST, o PATCH con ambos campos) como si lo atrapa la CHECK de la
# base de datos (PATCH que cambia solo uno de los dos).
_IDENTIFICADOR_INVALIDO = (
    "Con tipo_identificador='radicado_unificado' el identificador debe "
    "tener exactamente 23 dígitos"
)


def _respuesta_integridad(error: IntegrityError) -> HTTPException:
    """Distingue por SQLSTATE, no por mensaje (mismo criterio que el arreglo
    42ac01d: Postgres traduce los mensajes según `lc_messages`, los códigos
    no). 23505 = unique_violation (identificador duplicado); 23514 =
    check_violation (la CHECK condicional de 23 dígitos,
    ck_expedientes_identificador_radicado_unificado_23_digitos), que es un
    error de validación del cliente, no un conflicto — 422, no 409."""
    if getattr(error.orig, "sqlstate", None) == "23514":
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=_IDENTIFICADOR_INVALIDO
        )
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_CONFLICTO_IDENTIFICADOR)


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
    except IntegrityError as error:
        db.rollback()
        raise _respuesta_integridad(error)


@router.get("", response_model=ExpedienteListaResponse)
def listar(
    limit: int = Query(default=LIMITE_POR_DEFECTO, ge=1, le=LIMITE_MAXIMO),
    offset: int = Query(default=0, ge=0),
    actor: ActorActual = Depends(usuario_actual_verificado),
    db: Session = Depends(get_db),
) -> ExpedienteListaResponse:
    items, total = expedientes.listar(db, actor.organizacion_id, limit, offset)
    return ExpedienteListaResponse(items=items, total=total)


@router.get("/{expediente_id}", response_model=ExpedienteResponse)
def obtener(
    expediente_id: uuid.UUID,
    actor: ActorActual = Depends(usuario_actual_verificado),
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
    except IntegrityError as error:
        db.rollback()
        raise _respuesta_integridad(error)


@router.post("/{expediente_id}/archivar", response_model=ExpedienteResponse)
def archivar(
    expediente_id: uuid.UUID,
    actor: ActorActual = Depends(usuario_actual_verificado),
    db: Session = Depends(get_db),
) -> Expediente:
    expediente = _obtener_o_404(db, actor.organizacion_id, expediente_id)
    return expedientes.archivar(db, actor.organizacion_id, actor.usuario_id, expediente)
