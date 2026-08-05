"""El tenant. Toda tabla de negocio cuelga de una organización (TenantMixin)."""
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IDMixin


class Organizacion(Base, IDMixin):
    __tablename__ = "organizaciones"

    nombre: Mapped[str] = mapped_column(String(255), nullable=False)
