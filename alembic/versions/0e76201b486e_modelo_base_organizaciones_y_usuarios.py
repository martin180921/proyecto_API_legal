"""modelo base: organizaciones y usuarios

Revision ID: 0e76201b486e
Revises: 
Create Date: 2026-08-05 00:01:37.094736

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0e76201b486e'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "organizaciones",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "creado_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("nombre", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "usuarios",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "creado_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("organizacion_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("contrasena_hash", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organizacion_id"], ["organizaciones.id"]),
        # El email es único DENTRO de una organización, no en toda la
        # plataforma: la misma persona puede ser usuaria de dos firmas.
        # Decisión de tenancy registrada en la bóveda el 2026-08-05
        # ([[Email único por organización, no global]]).
        sa.UniqueConstraint("organizacion_id", "email", name="uq_usuarios_organizacion_email"),
    )
    op.create_index(
        op.f("ix_usuarios_organizacion_id"), "usuarios", ["organizacion_id"], unique=False
    )
    op.create_index(op.f("ix_usuarios_email"), "usuarios", ["email"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_usuarios_email"), table_name="usuarios")
    op.drop_index(op.f("ix_usuarios_organizacion_id"), table_name="usuarios")
    op.drop_table("usuarios")
    op.drop_table("organizaciones")
