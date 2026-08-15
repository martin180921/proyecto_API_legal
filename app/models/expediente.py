"""Expediente judicial. Pertenece a una organización (TenantMixin).

`radicado` son 23 dígitos exactos ([[2026-08-04 Excel de procesos activos y
control diario]]), único **por organización**, no global: dos firmas pueden
llevar el mismo proceso desde extremos distintos, así que no hay motivo para
prohibir el mismo radicado entre organizaciones. `tipo_proceso` se limita a
civil | administrativo — los expedientes de responsabilidad fiscal ante
Contraloría quedan fuera de la Fase 1 mientras la pregunta abierta de
[[Flujo central de Fase 1 — seguimiento de expedientes judiciales]] no diga
otra cosa.

`juzgado`, `despacho`, `partes` y `ultima_actuacion_conocida` son opcionales:
un expediente recién dado de alta puede no tener todavía todos los datos que
sí trae el Excel de Juan Diego para procesos ya en curso.
"""
import enum

from sqlalchemy import Boolean, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TenantMixin


class TipoProceso(str, enum.Enum):
    CIVIL = "civil"
    ADMINISTRATIVO = "administrativo"


class Expediente(Base, TenantMixin):
    __tablename__ = "expedientes"

    __table_args__ = (
        UniqueConstraint(
            "organizacion_id", "radicado", name="uq_expedientes_organizacion_radicado"
        ),
    )

    radicado: Mapped[str] = mapped_column(String(23), nullable=False)
    juzgado: Mapped[str | None] = mapped_column(String(255), nullable=True)
    despacho: Mapped[str | None] = mapped_column(String(255), nullable=True)
    partes: Mapped[str | None] = mapped_column(Text, nullable=True)
    tipo_proceso: Mapped[TipoProceso] = mapped_column(
        SAEnum(
            TipoProceso,
            name="tipo_proceso",
            native_enum=False,
            length=20,
            create_constraint=False,
            values_callable=lambda enum_cls: [miembro.value for miembro in enum_cls],
        ),
        nullable=False,
    )
    ultima_actuacion_conocida: Mapped[str | None] = mapped_column(Text, nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
