"""Usuario de la plataforma. Pertenece a una organización (TenantMixin).

`contrasena_hash` solo almacena el hash — el hash/verificación en sí (bcrypt)
y los endpoints de auth son T4, fuera de esta tarea.

**El email es único por organización, no globalmente**
([[Email único por organización, no global]], bóveda, 2026-08-05). La misma
persona puede existir en dos firmas con el mismo correo. Consecuencia directa
para T4: el login no puede resolver al usuario solo con el email — necesita
además la organización (subdominio o campo explícito).

`nombre` (A.2.4, Bloque A3, 2026-08-21) hace falta para la regla 7 de Juan
Diego: alerta por correo al abogado responsable de un expediente
(`Expediente.responsable_usuario_id`) necesita un nombre a quien dirigirse,
no solo un email. Obligatorio: la migración hace *backfill* de los usuarios
existentes a partir de la parte local de su email, porque no hay forma de
confirmar contra producción (fuera de alcance de esta sesión) cuántos
usuarios reales existen hoy sin nombre.

`activo` (A.1.3, Bloque A3, 2026-08-21) es lo que permite revocar el acceso
de un usuario sin esperar a que expire su JWT (hasta 8 horas): las rutas que
mutan datos usan `usuario_actual_verificado`
(`app/core/security.py`), que comprueba este campo contra la base en cada
petición.
"""
from sqlalchemy import Boolean, String, UniqueConstraint
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
    nombre: Mapped[str] = mapped_column(String(255), nullable=False)
    contrasena_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
