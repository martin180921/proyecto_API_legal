"""expedientes: modelo y CRUD (Etapa Entrada, S3-4)

Revision ID: 83e6acf6b885
Revises: 91bd238ab035
Create Date: 2026-08-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '83e6acf6b885'
down_revision: Union[str, Sequence[str], None] = '91bd238ab035'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "expedientes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "creado_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("organizacion_id", sa.Uuid(), nullable=False),
        sa.Column("radicado", sa.String(length=23), nullable=False),
        sa.Column("juzgado", sa.String(length=255), nullable=True),
        sa.Column("despacho", sa.String(length=255), nullable=True),
        sa.Column("partes", sa.Text(), nullable=True),
        sa.Column("tipo_proceso", sa.String(length=20), nullable=False),
        sa.Column("ultima_actuacion_conocida", sa.Text(), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organizacion_id"], ["organizaciones.id"]),
        # Único por organización, no global: dos firmas pueden llevar el mismo
        # radicado desde extremos distintos.
        sa.UniqueConstraint(
            "organizacion_id", "radicado", name="uq_expedientes_organizacion_radicado"
        ),
        # Validación en dos capas, como el resto del proyecto (PRAGMA
        # foreign_keys en los tests, hash de contraseña + JWT en T4): Pydantic
        # rechaza un radicado inválido en el borde, y esta CHECK cierra la vía
        # de cualquier escritura que no pase por la API.
        sa.CheckConstraint("radicado ~ '^[0-9]{23}$'", name="ck_expedientes_radicado_23_digitos"),
        sa.CheckConstraint(
            "tipo_proceso IN ('civil', 'administrativo')", name="ck_expedientes_tipo_proceso"
        ),
    )
    op.create_index(
        op.f("ix_expedientes_organizacion_id"), "expedientes", ["organizacion_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_expedientes_organizacion_id"), table_name="expedientes")
    op.drop_table("expedientes")
