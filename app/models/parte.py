"""Partes procesales de un expediente (A.2.2, Bloque A3, 2026-08-21).

Tabla estructurada, aparte de `Expediente.partes` (texto libre de
importación, que se conserva sin cambios): el spike de P4 encontró que
`GET /Proceso/Sujetos/{idProceso}` da partes estructuradas — `tipoSujeto`
(Demandante/Demandado), `nombreRazonSocial`, `identificacion`,
`esEmplazado` — mejor fuente que el texto concatenado del Excel. El
importador la llena con lo poco que puede sacar del Excel; el conector (fuera
de esta sesión) la corregirá con lo bueno cuando resuelva el expediente.

`origen` distingue de dónde vino cada fila: `importacion` (Excel) o
`conector` (Rama Judicial, todavía sin construir).

Lleva `organizacion_id` propio vía `TenantMixin`, aunque es derivable de
`expediente_id` — el proyecto no hace excepciones a "toda tabla de negocio
lleva `organizacion_id`" (invariante de multi-tenancy), mismo criterio que ya
sigue `EventoAuditoria` con su propio `organizacion_id` pese a que
`entidad_id` podría, en teoría, resolverlo indirectamente.
"""
import enum
import uuid

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TenantMixin


class OrigenParte(str, enum.Enum):
    IMPORTACION = "importacion"
    CONECTOR = "conector"


class Parte(Base, TenantMixin):
    __tablename__ = "partes"

    expediente_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("expedientes.id"), nullable=False, index=True
    )
    tipo: Mapped[str] = mapped_column(String(100), nullable=False)
    nombre: Mapped[str] = mapped_column(String(255), nullable=False)
    identificacion: Mapped[str | None] = mapped_column(String(50), nullable=True)
    origen: Mapped[OrigenParte] = mapped_column(
        SAEnum(
            OrigenParte,
            name="origen_parte",
            native_enum=False,
            length=20,
            create_constraint=False,
            values_callable=lambda enum_cls: [miembro.value for miembro in enum_cls],
        ),
        nullable=False,
    )
