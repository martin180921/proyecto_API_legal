"""Usuario de la plataforma. Pertenece a una organización (TenantMixin).

`contrasena_hash` solo almacena el hash — el hash/verificación en sí (bcrypt)
y los endpoints de auth son T4, fuera de esta tarea.
"""
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TenantMixin


class Usuario(Base, TenantMixin):
    __tablename__ = "usuarios"

    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    contrasena_hash: Mapped[str] = mapped_column(String(255), nullable=False)
