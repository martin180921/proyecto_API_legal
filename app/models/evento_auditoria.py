"""Audit log de solo INSERT ([[Multi-tenancy y audit log desde el día 1]]).

Este modelo no define ninguna columna ni relación pensada para actualizarse, y
`app/services/auditoria.py` es la única vía de escritura — expone `registrar()`
y nada más. No añadir aquí un mixin ni un método de actualización.

Sobre la inmutabilidad, con precisión: la migración revoca UPDATE, DELETE y
TRUNCATE al rol de la app, pero ese rol es hoy el mismo que corre las
migraciones y es owner de la tabla, y un owner puede volver a concederse los
permisos. Peor: si el rol fuera **superusuario** — que es lo que Railway
entrega por defecto — el REVOKE no haría absolutamente nada, porque un
superusuario de Postgres se salta los permisos. La barrera real exige rol de
migración ≠ rol de app, ninguno superusuario. Riesgo residual aceptado para el
piloto y anotado como tal en la bóveda; el arreglo se hace en F3, no aquí.

`entidad_id` es nullable a propósito: hay eventos auditables que no apuntan a
ninguna fila — el rate-limit de login por IP de T4 es el caso que fuerza la
decisión. `entidad` sigue NOT NULL, así que el evento nunca pierde su tipo.
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
    entidad_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    detalle: Mapped[dict[str, Any] | None] = mapped_column(JSONVariante, nullable=True)
