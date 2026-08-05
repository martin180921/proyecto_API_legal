"""audit log inmutable

Revision ID: 076570ed21f0
Revises: 0e76201b486e
Create Date: 2026-08-05 00:25:37.856269

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '076570ed21f0'
down_revision: Union[str, Sequence[str], None] = '0e76201b486e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "eventos_auditoria",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organizacion_id", sa.Uuid(), nullable=False),
        sa.Column("usuario_id", sa.Uuid(), nullable=True),
        sa.Column("accion", sa.String(length=255), nullable=False),
        sa.Column("entidad", sa.String(length=255), nullable=False),
        sa.Column("entidad_id", sa.Uuid(), nullable=False),
        sa.Column(
            "detalle",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organizacion_id"], ["organizaciones.id"]),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"]),
    )
    op.create_index(
        op.f("ix_eventos_auditoria_organizacion_id"),
        "eventos_auditoria",
        ["organizacion_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_eventos_auditoria_usuario_id"), "eventos_auditoria", ["usuario_id"], unique=False
    )
    op.create_index(
        op.f("ix_eventos_auditoria_entidad_id"), "eventos_auditoria", ["entidad_id"], unique=False
    )

    # Inmutabilidad a nivel de base de datos, no solo por convención de
    # código: el rol que usa la app (el mismo que corre esta migración,
    # CURRENT_USER) pierde UPDATE/DELETE sobre esta tabla para siempre.
    # Revisión de seguridad 2026-08-05, [[Plan técnico por fases#T3]].
    op.execute("REVOKE UPDATE, DELETE ON eventos_auditoria FROM CURRENT_USER")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("GRANT UPDATE, DELETE ON eventos_auditoria TO CURRENT_USER")
    op.drop_index(op.f("ix_eventos_auditoria_entidad_id"), table_name="eventos_auditoria")
    op.drop_index(op.f("ix_eventos_auditoria_usuario_id"), table_name="eventos_auditoria")
    op.drop_index(op.f("ix_eventos_auditoria_organizacion_id"), table_name="eventos_auditoria")
    op.drop_table("eventos_auditoria")
