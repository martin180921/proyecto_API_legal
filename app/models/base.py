"""Mixins comunes a todos los modelos.

`organizacion_id` NOT NULL en toda tabla de negocio, decidido en
`Multi-tenancy y audit log desde el día 1` (bóveda, API Legal/Decisiones/):
el retrofit de multi-tenancy es de los refactors más caros que existen, y el
coste de tenerlo desde ahora es cercano a cero.

`id` es UUID (no entero autoincremental): no expone el conteo de filas ni el
orden de creación, relevante porque la API se piensa desde el día 1 para
abrirse a bancos y Estado. `sqlalchemy.Uuid` es agnóstico de motor — mismo
tipo en SQLite (tests) y Postgres (producción).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Uuid
from sqlalchemy.orm import Mapped, mapped_column


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


class IDMixin:
    """id + creado_en. Lo usa toda tabla, incluida `organizaciones` (el propio tenant)."""

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_ahora, nullable=False
    )


class TenantMixin(IDMixin):
    """IDMixin + organizacion_id NOT NULL. Lo usa toda tabla de negocio salvo `organizaciones`."""

    organizacion_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizaciones.id"), nullable=False, index=True
    )
