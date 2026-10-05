"""revisiones y actuaciones (Etapa Procesamiento)

Tres pasos, en este orden (cada uno es requisito del siguiente):

1. `UNIQUE (organizacion_id, id)` en `procesos_fuente` — sin esto la FK
   compuesta desde `actuaciones` no es posible (mismo patrón de A5.3, R.3).
2. Crear `revisiones` (cuatro resultados: con_novedad, sin_novedad,
   no_verificado, no_encontrado), con su propio `UNIQUE (organizacion_id,
   id)` para la FK de `actuaciones`.
3. Crear `actuaciones`, con FK compuestas a `procesos_fuente` y `revisiones`
   y `UNIQUE (organizacion_id, proceso_fuente_id, id_externo)`, que hace
   idempotente una corrida repetida.

Solo añade tablas e índices: no toca datos existentes. El `downgrade` aborta
si hay filas en `actuaciones` o `revisiones`: son el registro de lo que el
sistema afirmó haber revisado, y borrarlas en silencio sería perder esa
evidencia.

Revision ID: c3a1d7e92b40
Revises: ff9f88fd550c
Create Date: 2026-10-05 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c3a1d7e92b40'
down_revision: Union[str, Sequence[str], None] = 'ff9f88fd550c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- 1. UNIQUE (organizacion_id, id) en procesos_fuente ------------------
    op.create_unique_constraint(
        "uq_procesos_fuente_organizacion_id", "procesos_fuente", ["organizacion_id", "id"]
    )

    # --- 2. revisiones ----------------------------------------------------------
    op.create_table(
        "revisiones",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("organizacion_id", sa.Uuid(), nullable=False),
        sa.Column("expediente_id", sa.Uuid(), nullable=False),
        sa.Column("fuente", sa.String(length=30), nullable=False),
        sa.Column("resultado", sa.String(length=20), nullable=False),
        sa.Column(
            "revisado_en", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("corrida_id", sa.Uuid(), nullable=True),
        sa.Column("detalle", sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organizacion_id"], ["organizaciones.id"]),
        sa.ForeignKeyConstraint(
            ["organizacion_id", "expediente_id"],
            ["expedientes.organizacion_id", "expedientes.id"],
            name="fk_revisiones_expediente_organizacion",
        ),
        sa.UniqueConstraint("organizacion_id", "id", name="uq_revisiones_organizacion_id"),
        sa.CheckConstraint("fuente IN ('rama_judicial')", name="ck_revisiones_fuente"),
        sa.CheckConstraint(
            "resultado IN ('con_novedad', 'sin_novedad', 'no_verificado', 'no_encontrado')",
            name="ck_revisiones_resultado",
        ),
    )
    op.create_index(op.f("ix_revisiones_organizacion_id"), "revisiones", ["organizacion_id"])
    op.create_index(op.f("ix_revisiones_expediente_id"), "revisiones", ["expediente_id"])
    op.create_index(op.f("ix_revisiones_corrida_id"), "revisiones", ["corrida_id"])

    # --- 3. actuaciones ---------------------------------------------------------
    op.create_table(
        "actuaciones",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("organizacion_id", sa.Uuid(), nullable=False),
        sa.Column("proceso_fuente_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        # BigInteger: idRegActuacion ya supera int32 (2.694.826.740).
        sa.Column("id_externo", sa.BigInteger(), nullable=False),
        sa.Column("consecutivo", sa.Integer(), nullable=False),
        sa.Column("fecha_actuacion", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tipo", sa.String(length=255), nullable=False),
        sa.Column("anotacion", sa.Text(), nullable=True),
        sa.Column("fecha_inicial", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fecha_final", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fecha_registro", sa.DateTime(timezone=True), nullable=True),
        sa.Column("con_documentos", sa.Boolean(), nullable=False),
        sa.Column("crudo", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organizacion_id"], ["organizaciones.id"]),
        sa.ForeignKeyConstraint(
            ["organizacion_id", "proceso_fuente_id"],
            ["procesos_fuente.organizacion_id", "procesos_fuente.id"],
            name="fk_actuaciones_proceso_fuente_organizacion",
        ),
        sa.ForeignKeyConstraint(
            ["organizacion_id", "revision_id"],
            ["revisiones.organizacion_id", "revisiones.id"],
            name="fk_actuaciones_revision_organizacion",
        ),
        sa.UniqueConstraint(
            "organizacion_id",
            "proceso_fuente_id",
            "id_externo",
            name="uq_actuaciones_organizacion_proceso_id_externo",
        ),
    )
    op.create_index(op.f("ix_actuaciones_organizacion_id"), "actuaciones", ["organizacion_id"])
    op.create_index(op.f("ix_actuaciones_proceso_fuente_id"), "actuaciones", ["proceso_fuente_id"])
    op.create_index(op.f("ix_actuaciones_revision_id"), "actuaciones", ["revision_id"])


def downgrade() -> None:
    """Downgrade schema."""
    conexion = op.get_bind()
    for tabla in ("actuaciones", "revisiones"):
        filas = conexion.execute(sa.text(f"SELECT count(*) FROM {tabla}")).scalar_one()
        if filas:
            raise RuntimeError(
                f"No se puede revertir: {tabla} tiene {filas} fila(s). Son el registro de "
                "lo que el sistema afirmó haber revisado; no se borran en silencio."
            )

    op.drop_index(op.f("ix_actuaciones_revision_id"), table_name="actuaciones")
    op.drop_index(op.f("ix_actuaciones_proceso_fuente_id"), table_name="actuaciones")
    op.drop_index(op.f("ix_actuaciones_organizacion_id"), table_name="actuaciones")
    op.drop_table("actuaciones")

    op.drop_index(op.f("ix_revisiones_corrida_id"), table_name="revisiones")
    op.drop_index(op.f("ix_revisiones_expediente_id"), table_name="revisiones")
    op.drop_index(op.f("ix_revisiones_organizacion_id"), table_name="revisiones")
    op.drop_table("revisiones")

    op.drop_constraint("uq_procesos_fuente_organizacion_id", "procesos_fuente", type_="unique")
