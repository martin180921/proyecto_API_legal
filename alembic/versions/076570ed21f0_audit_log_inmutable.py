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
        # Timestamp del servidor de BD, no del proceso de la app: para un
        # registro con posible valor probatorio, el reloj de Postgres es más
        # defendible que el del contenedor. Revisión de seguridad 2026-08-05.
        sa.Column(
            "creado_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("organizacion_id", sa.Uuid(), nullable=False),
        sa.Column("usuario_id", sa.Uuid(), nullable=True),
        sa.Column("accion", sa.String(length=255), nullable=False),
        sa.Column("entidad", sa.String(length=255), nullable=False),
        # Nullable: hay eventos auditables que no apuntan a ninguna fila —
        # el rate-limit de login por IP de T4 es el caso que lo fuerza.
        # `entidad` sigue NOT NULL, así que el evento conserva su tipo.
        sa.Column("entidad_id", sa.Uuid(), nullable=True),
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

    # Barrera de base de datos, no solo convención de código: el rol de la
    # app pierde UPDATE/DELETE/TRUNCATE sobre esta tabla. Cierra el borrado
    # accidental desde el ORM o desde una consola.
    #
    # TRUNCATE va incluido y no es un extra: es un permiso aparte de DELETE en
    # Postgres, así que revocar solo UPDATE/DELETE dejaba abierto un
    # `TRUNCATE eventos_auditoria` que vacía la tabla entera de un golpe.
    # Detectado el 2026-08-05 leyendo los permisos reales en una Postgres de
    # verdad — el hueco existía desde T3 y no se veía en el código.
    #
    # RIESGO RESIDUAL ACEPTADO (2026-08-05): esto NO es inmutabilidad fuerte.
    # CURRENT_USER es aquí el rol que corre las migraciones, que es el mismo
    # de la app y owner de la tabla — y un owner puede volver a concederse
    # UPDATE/DELETE cuando quiera. La inmutabilidad real exige rol de
    # migración ≠ rol de app (y, si se quiere ir más lejos, un trigger BEFORE
    # UPDATE/DELETE que lance excepción). Se acepta así para el piloto y se
    # arregla en F3. No afirmar por ahí que «no existe vía para modificarlo».
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON eventos_auditoria FROM CURRENT_USER")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("GRANT UPDATE, DELETE, TRUNCATE ON eventos_auditoria TO CURRENT_USER")
    op.drop_index(op.f("ix_eventos_auditoria_entidad_id"), table_name="eventos_auditoria")
    op.drop_index(op.f("ix_eventos_auditoria_usuario_id"), table_name="eventos_auditoria")
    op.drop_index(op.f("ix_eventos_auditoria_organizacion_id"), table_name="eventos_auditoria")
    op.drop_table("eventos_auditoria")
