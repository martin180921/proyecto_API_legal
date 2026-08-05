"""Usuario de la plataforma. Pertenece a una organización (TenantMixin).

`contrasena_hash` solo almacena el hash — el hash/verificación en sí (bcrypt)
y los endpoints de auth son T4, fuera de esta tarea.

**El email es único por organización, no globalmente**
([[Email único por organización, no global]], bóveda, 2026-08-05). La misma
persona puede existir en dos firmas con el mismo correo. Consecuencia directa
para T4: el login no puede resolver al usuario solo con el email — necesita
además la organización (subdominio o campo explícito).
"""
from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TenantMixin


class Usuario(Base, TenantMixin):
    __tablename__ = "usuarios"

    __table_args__ = (
        UniqueConstraint("organizacion_id", "email", name="uq_usuarios_organizacion_email"),
    )

    # Índice no único: sirve para buscar por email dentro de una organización.
    # La unicidad la impone `uq_usuarios_organizacion_email`, no este índice.
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    contrasena_hash: Mapped[str] = mapped_column(String(255), nullable=False)
