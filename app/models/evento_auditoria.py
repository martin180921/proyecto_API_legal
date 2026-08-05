"""Audit log inmutable ([[Multi-tenancy y audit log desde el día 1]]).

Solo INSERT: este modelo no define ninguna columna ni relación pensada para
actualizarse, y `app/services/auditoria.py` es la única vía de escritura —
expone `registrar()` y nada más. La inmutabilidad real la da la base de
datos: la migración que crea esta tabla revoca UPDATE/DELETE al rol que usa
la app. No añadir aquí un mixin ni un método de actualización.
"""
import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.core.db import Base
from app.models.base import TenantMixin

JSONVariante = JSON().with_variant(JSONB, "postgresql")


class EventoAuditoria(Base, TenantMixin):
    __tablename__ = "eventos_auditoria"

    usuario_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("usuarios.id"), nullable=True, index=True
    )
    accion: Mapped[str] = mapped_column(String(255), nullable=False)
    entidad: Mapped[str] = mapped_column(String(255), nullable=False)
    entidad_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    detalle: Mapped[dict[str, Any] | None] = mapped_column(JSONVariante, nullable=True)
