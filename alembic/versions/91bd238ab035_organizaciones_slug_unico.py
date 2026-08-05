"""organizaciones: slug único para resolver el login (T4)

Revision ID: 91bd238ab035
Revises: 076570ed21f0
Create Date: 2026-08-05 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '91bd238ab035'
down_revision: Union[str, Sequence[str], None] = '076570ed21f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # NOT NULL directo, sin server_default: no hay ninguna organización creada
    # todavía (el piloto no ha arrancado). Con filas reales, este ALTER TABLE
    # exigiría backfill antes de imponer NOT NULL + UNIQUE — igual que en la
    # revisión de P1, se aprovecha la ventana de cero filas.
    op.add_column("organizaciones", sa.Column("slug", sa.String(length=255), nullable=False))
    op.create_index(
        op.f("ix_organizaciones_slug"), "organizaciones", ["slug"], unique=True
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_organizaciones_slug"), table_name="organizaciones")
    op.drop_column("organizaciones", "slug")
