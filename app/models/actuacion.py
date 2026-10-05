"""Actuación de un proceso de la fuente (Etapa Procesamiento, reglas 3 y 4).

Cuelga de `ProcesoFuente`, no de `Expediente`: los consecutivos son por
`idProceso` y reinician si el proceso se remite (spike P4, C.1), así que la
unidad natural es el proceso de la fuente. El listado por expediente sale de
un join con `procesos_fuente` — «un hecho, un sitio», sin `expediente_id`
duplicado aquí.

`id_externo` es el `idRegActuacion`: **la clave del comparador de la regla 4**
(«solo lo nuevo»), no `consecutivo` ni las fechas — `fechaRegistro` puede ir
trece meses por detrás de `fechaActuacion`. `UNIQUE (organizacion_id,
proceso_fuente_id, id_externo)` hace idempotente una corrida repetida.

`fecha_inicial`/`fecha_final` se guardan **siempre**, nunca condicionadas al
tipo (spike P4, C.3): de ahí salen los términos procesales. `crudo` es el JSON
original de la fuente, para poder diagnosticar el día que cambie su forma.

`revision_id` apunta a la `Revision` en la que se descubrió: es lo que dice
qué fue «lo nuevo» de un `con_novedad`. FK compuesta con `organizacion_id` en
las dos relaciones (R.3): una actuación de la organización A no puede colgar
de un proceso ni de una revisión de la B.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TenantMixin


class Actuacion(Base, TenantMixin):
    __tablename__ = "actuaciones"

    __table_args__ = (
        UniqueConstraint(
            "organizacion_id",
            "proceso_fuente_id",
            "id_externo",
            name="uq_actuaciones_organizacion_proceso_id_externo",
        ),
        ForeignKeyConstraint(
            ["organizacion_id", "proceso_fuente_id"],
            ["procesos_fuente.organizacion_id", "procesos_fuente.id"],
            name="fk_actuaciones_proceso_fuente_organizacion",
        ),
        ForeignKeyConstraint(
            ["organizacion_id", "revision_id"],
            ["revisiones.organizacion_id", "revisiones.id"],
            name="fk_actuaciones_revision_organizacion",
        ),
    )

    proceso_fuente_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    revision_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    # BigInteger: `idRegActuacion` ya supera int32 (2.694.826.740).
    id_externo: Mapped[int] = mapped_column(BigInteger, nullable=False)
    consecutivo: Mapped[int] = mapped_column(Integer, nullable=False)
    fecha_actuacion: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    tipo: Mapped[str] = mapped_column(String(255), nullable=False)
    anotacion: Mapped[str | None] = mapped_column(Text, nullable=True)
    fecha_inicial: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fecha_final: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fecha_registro: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    con_documentos: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    crudo: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
