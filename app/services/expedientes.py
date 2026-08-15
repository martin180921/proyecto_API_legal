"""CRUD de expedientes (Etapa Entrada, S3–4).

Todo lector y toda mutación filtran por `organizacion_id`: nunca se confía en
el `id` solo, mismo patrón que ya usa `app/api/v1/auth.py` con `Usuario`
([[Multi-tenancy y audit log desde el día 1]]). Cada mutación deja su evento
en el audit log vía `app/services/auditoria.py` (regla 9 del documento de
Juan Diego).
"""
import uuid

from sqlalchemy.orm import Session

from app.models.expediente import Expediente
from app.schemas.expediente import ExpedienteActualizar, ExpedienteCrear
from app.services import auditoria


def crear(
    db: Session,
    organizacion_id: uuid.UUID,
    usuario_id: uuid.UUID,
    payload: ExpedienteCrear,
) -> Expediente:
    expediente = Expediente(organizacion_id=organizacion_id, **payload.model_dump())
    db.add(expediente)
    db.flush()

    auditoria.registrar(
        db,
        organizacion_id=organizacion_id,
        accion="crear",
        entidad="expediente",
        entidad_id=expediente.id,
        usuario_id=usuario_id,
    )
    db.commit()
    return expediente


def listar(
    db: Session, organizacion_id: uuid.UUID, limit: int, offset: int
) -> tuple[list[Expediente], int]:
    consulta = db.query(Expediente).filter_by(organizacion_id=organizacion_id)
    total = consulta.count()
    items = (
        consulta.order_by(Expediente.creado_en.desc()).offset(offset).limit(limit).all()
    )
    return items, total


def obtener(
    db: Session, organizacion_id: uuid.UUID, expediente_id: uuid.UUID
) -> Expediente | None:
    return (
        db.query(Expediente)
        .filter_by(organizacion_id=organizacion_id, id=expediente_id)
        .one_or_none()
    )


def actualizar(
    db: Session,
    organizacion_id: uuid.UUID,
    usuario_id: uuid.UUID,
    expediente: Expediente,
    payload: ExpedienteActualizar,
) -> Expediente:
    cambios = payload.model_dump(exclude_unset=True)
    for campo, valor in cambios.items():
        setattr(expediente, campo, valor)
    db.flush()

    auditoria.registrar(
        db,
        organizacion_id=organizacion_id,
        accion="actualizar",
        entidad="expediente",
        entidad_id=expediente.id,
        usuario_id=usuario_id,
        detalle={"campos": list(cambios.keys())},
    )
    db.commit()
    return expediente


def archivar(
    db: Session,
    organizacion_id: uuid.UUID,
    usuario_id: uuid.UUID,
    expediente: Expediente,
) -> Expediente:
    expediente.activo = False
    db.flush()

    auditoria.registrar(
        db,
        organizacion_id=organizacion_id,
        accion="archivar",
        entidad="expediente",
        entidad_id=expediente.id,
        usuario_id=usuario_id,
    )
    db.commit()
    return expediente
