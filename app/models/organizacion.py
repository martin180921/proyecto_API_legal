"""El tenant. Toda tabla de negocio cuelga de una organización (TenantMixin).

`slug` es el identificador que el login de T4 usa para resolver la
organización a partir de lo que escribe el usuario ([[Plan técnico por
fases]]): `nombre` no tiene restricción de unicidad (dos bufetes pueden
llamarse igual, y un bufete puede cambiar de nombre), así que no sirve como
clave de login. `slug` sí es único, generado una vez en el registro
(`app/api/v1/auth.py`) y pensado como estable — no se deriva del `nombre` en
tiempo de login, solo al crearlo.
"""
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IDMixin


class Organizacion(Base, IDMixin):
    __tablename__ = "organizaciones"

    nombre: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
