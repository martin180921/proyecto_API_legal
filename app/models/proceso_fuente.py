"""Proceso de una fuente externa asociado a un expediente (B.1-bis, A5.3,
2026-09-22). Sustituye el escalar `Expediente.id_proceso_rama`: el spike P4
revisado por el senior el 2026-09-11 (C.1) encontró que un radicado puede
devolver varios `idProceso`, y que un proceso remitido a otro despacho
continúa bajo uno distinto — un escalar se queda mirando una vía muerta y
reporta «sin novedad» sobre un expediente que sí se mueve. Ver
[[Relación expediente ↔ proceso de la fuente — B.1-bis]] en la bóveda.

`fuente` es texto + CHECK, no una tabla aparte a propósito: si mañana entra
SAMAI o TYBA, es una fila nueva con `fuente` distinto, no una migración ni
una tabla nueva.

Lleva `organizacion_id` propio vía `TenantMixin` (mismo criterio que ya sigue
`Parte`, aunque sea derivable de `expediente_id`), y la FK a `expedientes` es
**compuesta** `(organizacion_id, expediente_id)` — no basta con
`expediente_id` solo: eso permitiría un `ProcesoFuente` de la organización A
colgado de un expediente de la B (R.3, revisión del 2026-09-17).

Todos los campos salvo `id`/`creado_en`/`organizacion_id`/`expediente_id`/
`fuente`/`id_externo`/`estado` los escribe únicamente el motor
(`app/connectors/`, `app/services/revisor.py`, fuera de esta sesión). Nunca
son escribibles por el cliente — de ahí que la API solo exponga
`ProcesoFuenteResponse`, sin su contraparte `Actualizar` (R.4).
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TenantMixin


class FuenteProceso(str, enum.Enum):
    RAMA_JUDICIAL = "rama_judicial"


class EstadoProcesoFuente(str, enum.Enum):
    ACTIVO = "activo"
    REMITIDO = "remitido"
    DESAPARECIDO = "desaparecido"


class ProcesoFuente(Base, TenantMixin):
    __tablename__ = "procesos_fuente"

    __table_args__ = (
        UniqueConstraint(
            "organizacion_id",
            "fuente",
            "id_externo",
            name="uq_procesos_fuente_organizacion_fuente_id_externo",
        ),
        ForeignKeyConstraint(
            ["organizacion_id", "expediente_id"],
            ["expedientes.organizacion_id", "expedientes.id"],
            name="fk_procesos_fuente_expediente_organizacion",
        ),
    )

    expediente_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    fuente: Mapped[FuenteProceso] = mapped_column(
        SAEnum(
            FuenteProceso,
            name="fuente_proceso",
            native_enum=False,
            length=30,
            create_constraint=False,
            values_callable=lambda enum_cls: [miembro.value for miembro in enum_cls],
        ),
        nullable=False,
    )
    # BigInteger, no Integer: es el mismo `idProceso` que ya obligó a migrar
    # `Expediente.id_proceso_rama` a BigInteger en `bb46bdacfa57` (supera int32).
    id_externo: Mapped[int] = mapped_column(BigInteger, nullable=False)
    id_conexion: Mapped[int | None] = mapped_column(Integer, nullable=True)
    despacho: Mapped[str | None] = mapped_column(String(255), nullable=True)
    departamento: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Nunca visto en `true` (pregunta abierta del proyecto); se guarda igual
    # para poder explicarlo el día que aparezca uno.
    es_privado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ultima_actualizacion_fuente: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fecha_ultima_consulta: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    estado: Mapped[EstadoProcesoFuente] = mapped_column(
        SAEnum(
            EstadoProcesoFuente,
            name="estado_proceso_fuente",
            native_enum=False,
            length=20,
            create_constraint=False,
            values_callable=lambda enum_cls: [miembro.value for miembro in enum_cls],
        ),
        nullable=False,
    )
