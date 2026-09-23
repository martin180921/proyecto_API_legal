"""CRUD de expedientes (Etapa Entrada, S3–4).

Todo lector y toda mutación filtran por `organizacion_id`: nunca se confía en
el `id` solo, mismo patrón que ya usa `app/api/v1/auth.py` con `Usuario`
([[Multi-tenancy y audit log desde el día 1]]). Cada mutación deja su evento
en el audit log vía `app/services/auditoria.py` (regla 9 del documento de
Juan Diego).
"""
import enum
import uuid

from sqlalchemy import exists, or_
from sqlalchemy.orm import Session

from app.models.expediente import Expediente, Seguimiento, TipoProceso
from app.models.parte import Parte
from app.models.usuario import Usuario
from app.schemas.expediente import ExpedienteActualizar, ExpedienteCrear
from app.services import auditoria


class OrdenExpedientes(str, enum.Enum):
    """Lista cerrada (C.4, Bloque C): un `ordenar` que no está aquí da 422 —
    lo hace FastAPI solo, al tipar el query param con este enum —, no se
    ignora en silencio. `urgencia` se añade cuando exista
    `app/services/terminos.py` (Etapa Procesamiento)."""

    CREADO_EN = "creado_en"
    CREADO_EN_DESC = "-creado_en"
    IDENTIFICADOR = "identificador"


_COLUMNA_DE_ORDEN = {
    OrdenExpedientes.CREADO_EN: Expediente.creado_en.asc(),
    OrdenExpedientes.CREADO_EN_DESC: Expediente.creado_en.desc(),
    OrdenExpedientes.IDENTIFICADOR: Expediente.identificador.asc(),
}


class ResponsableInvalido(Exception):
    """`responsable_usuario_id` no es un usuario activo de la MISMA
    organización que el expediente (R.3, revisión del 2026-09-17). Antes de
    A5.3 un UUID inexistente o de otra organización violaba la FK simple con
    un `IntegrityError` que el router traducía —por error— en 409 «ya existe
    un expediente con ese identificador», un mensaje falso."""


def _validar_responsable(
    db: Session, organizacion_id: uuid.UUID, responsable_id: uuid.UUID | None
) -> None:
    if responsable_id is None:
        return
    existe = (
        db.query(Usuario.id)
        .filter_by(id=responsable_id, organizacion_id=organizacion_id, activo=True)
        .first()
    )
    if existe is None:
        raise ResponsableInvalido()


def crear(
    db: Session,
    organizacion_id: uuid.UUID,
    usuario_id: uuid.UUID,
    payload: ExpedienteCrear,
) -> Expediente:
    _validar_responsable(db, organizacion_id, payload.responsable_usuario_id)
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
    db: Session,
    organizacion_id: uuid.UUID,
    limit: int,
    offset: int,
    *,
    q: str | None = None,
    activo: bool | None = None,
    seguimiento: Seguimiento | None = None,
    tipo_proceso: TipoProceso | None = None,
    responsable_id: uuid.UUID | None = None,
    ordenar: OrdenExpedientes = OrdenExpedientes.CREADO_EN_DESC,
) -> tuple[list[Expediente], int]:
    consulta = db.query(Expediente).filter_by(organizacion_id=organizacion_id)

    if activo is not None:
        consulta = consulta.filter(Expediente.activo == activo)
    if seguimiento is not None:
        consulta = consulta.filter(Expediente.seguimiento == seguimiento)
    if tipo_proceso is not None:
        consulta = consulta.filter(Expediente.tipo_proceso == tipo_proceso)
    if responsable_id is not None:
        consulta = consulta.filter(Expediente.responsable_usuario_id == responsable_id)
    if q:
        # Con el tamaño del piloto (70 expedientes) un `ILIKE` sin índice
        # basta; anotado para cuando haya miles: índice `pg_trgm` sobre estas
        # columnas (C.4, Bloque C). `partes.nombre` es la tabla estructurada
        # (A.2.2) — se busca con `EXISTS`, no con un `join`, para no duplicar
        # el expediente por cada parte que matchee (rompería `total`).
        patron = f"%{q}%"
        existe_parte_que_coincide = exists().where(
            Parte.organizacion_id == Expediente.organizacion_id,
            Parte.expediente_id == Expediente.id,
            Parte.nombre.ilike(patron),
        )
        consulta = consulta.filter(
            or_(
                Expediente.identificador.ilike(patron),
                Expediente.juzgado.ilike(patron),
                Expediente.despacho.ilike(patron),
                Expediente.partes.ilike(patron),
                existe_parte_que_coincide,
            )
        )

    total = consulta.count()
    items = (
        consulta.order_by(_COLUMNA_DE_ORDEN[ordenar], Expediente.id)
        # Desempate por `id` siempre (C.4): `order_by(creado_en...)` a secas
        # puede repetir o saltarse filas entre páginas cuando hay empates
        # (dos expedientes con el mismo `creado_en`, posible con
        # `server_default=func.now()` en inserciones dentro de la misma
        # transacción — ver `scripts/importar_excel.py`).
        .offset(offset)
        .limit(limit)
        .all()
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
    if "responsable_usuario_id" in cambios:
        _validar_responsable(db, organizacion_id, cambios["responsable_usuario_id"])
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
