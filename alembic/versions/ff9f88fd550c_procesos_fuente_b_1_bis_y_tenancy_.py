"""procesos_fuente B.1-bis y tenancy compuesta (A5.3, R.3, R.4)

Migración única del Bloque A5, paso A5.3 (revisión integral del 2026-09-17,
[[Relación expediente ↔ proceso de la fuente — B.1-bis]]). Seis pasos, en
este orden exacto (el orden importa: cada uno es requisito del siguiente):

1. `UNIQUE (organizacion_id, id)` en `usuarios` y en `expedientes` — sin esto
   ninguna FK compuesta que apunte a ellas es posible.
2. Crear `procesos_fuente`, con `UNIQUE (organizacion_id, fuente,
   id_externo)` y FK compuesta `(organizacion_id, expediente_id) ->
   expedientes (organizacion_id, id)`.
3. Sustituir en `partes` y en `expedientes.responsable_usuario_id` las FK
   simples por compuestas — cierra R.3: antes de esto, la base aceptaba una
   `Parte` o un responsable de una organización colgados de un expediente de
   otra.
4. Guarda: si `id_proceso_rama`, `fecha_ultima_consulta` o
   `ultimo_consecutivo_visto` tienen algún dato, abortar. Se espera cero —
   el conector que los llenaría no existe todavía —, pero no se supone: se
   comprueba, mismo criterio que la guarda del downgrade de `f33c85dbb2f8`.
5. `DROP` de esas tres columnas: el estado del motor pasa a vivir en
   `procesos_fuente`, nunca escribible por el cliente (R.4).
6. El `downgrade` las recrea, y aborta si `procesos_fuente` tiene filas: no
   hay forma reversible de reconstruir un escalar a partir de una relación
   1:N sin inventar cuál de los procesos era "el" proceso.

Revision ID: ff9f88fd550c
Revises: bb46bdacfa57
Create Date: 2026-09-22 17:06:12.293916

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ff9f88fd550c'
down_revision: Union[str, Sequence[str], None] = 'bb46bdacfa57'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- 1. UNIQUE (organizacion_id, id) -------------------------------------
    op.create_unique_constraint("uq_usuarios_organizacion_id", "usuarios", ["organizacion_id", "id"])
    op.create_unique_constraint(
        "uq_expedientes_organizacion_id", "expedientes", ["organizacion_id", "id"]
    )

    # --- 2. Tabla procesos_fuente ---------------------------------------------
    op.create_table(
        "procesos_fuente",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "creado_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("organizacion_id", sa.Uuid(), nullable=False),
        sa.Column("expediente_id", sa.Uuid(), nullable=False),
        sa.Column("fuente", sa.String(length=30), nullable=False),
        # BigInteger, no Integer: el mismo idProceso que ya obligó a migrar
        # Expediente.id_proceso_rama en bb46bdacfa57 (supera int32).
        sa.Column("id_externo", sa.BigInteger(), nullable=False),
        sa.Column("id_conexion", sa.Integer(), nullable=True),
        sa.Column("despacho", sa.String(length=255), nullable=True),
        sa.Column("departamento", sa.String(length=255), nullable=True),
        sa.Column("es_privado", sa.Boolean(), nullable=False),
        sa.Column(
            "ultima_actualizacion_fuente", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("fecha_ultima_consulta", sa.DateTime(timezone=True), nullable=True),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organizacion_id"], ["organizaciones.id"]),
        sa.ForeignKeyConstraint(
            ["organizacion_id", "expediente_id"],
            ["expedientes.organizacion_id", "expedientes.id"],
            name="fk_procesos_fuente_expediente_organizacion",
        ),
        sa.UniqueConstraint(
            "organizacion_id",
            "fuente",
            "id_externo",
            name="uq_procesos_fuente_organizacion_fuente_id_externo",
        ),
        sa.CheckConstraint("fuente IN ('rama_judicial')", name="ck_procesos_fuente_fuente"),
        sa.CheckConstraint(
            "estado IN ('activo', 'remitido', 'desaparecido')", name="ck_procesos_fuente_estado"
        ),
    )
    op.create_index(
        op.f("ix_procesos_fuente_organizacion_id"), "procesos_fuente", ["organizacion_id"], unique=False
    )
    op.create_index(
        op.f("ix_procesos_fuente_expediente_id"), "procesos_fuente", ["expediente_id"], unique=False
    )

    # --- 3. FK simples -> compuestas (R.3) ------------------------------------
    op.drop_constraint("partes_expediente_id_fkey", "partes", type_="foreignkey")
    op.create_foreign_key(
        "fk_partes_expediente_organizacion",
        "partes",
        "expedientes",
        ["organizacion_id", "expediente_id"],
        ["organizacion_id", "id"],
    )

    op.drop_constraint(
        "fk_expedientes_responsable_usuario_id_usuarios", "expedientes", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_expedientes_responsable_organizacion",
        "expedientes",
        "usuarios",
        ["organizacion_id", "responsable_usuario_id"],
        ["organizacion_id", "id"],
    )

    # --- 4. Guarda: los tres campos del motor deben estar en NULL ------------
    conexion = op.get_bind()
    filas_con_datos = conexion.execute(
        sa.text(
            "SELECT count(*) FROM expedientes WHERE id_proceso_rama IS NOT NULL "
            "OR fecha_ultima_consulta IS NOT NULL OR ultimo_consecutivo_visto IS NOT NULL"
        )
    ).scalar_one()
    if filas_con_datos:
        raise RuntimeError(
            f"No se puede migrar: hay {filas_con_datos} expediente(s) con "
            "id_proceso_rama, fecha_ultima_consulta o ultimo_consecutivo_visto "
            "distintos de NULL. Ningún código de app/ escribe hoy esos campos "
            "(el conector no existe todavía), así que se esperaba cero — "
            "revisar el origen de esos datos antes de continuar; migrarlos a "
            "procesos_fuente a mano si son legítimos."
        )

    # --- 5. DROP de las tres columnas del motor -------------------------------
    op.drop_column("expedientes", "id_proceso_rama")
    op.drop_column("expedientes", "fecha_ultima_consulta")
    op.drop_column("expedientes", "ultimo_consecutivo_visto")


def downgrade() -> None:
    """Downgrade schema."""
    # --- 6. Guarda: no hay downgrade seguro con procesos_fuente pobladO ------
    # No es reversible sin pérdida: procesos_fuente es una relación 1:N y el
    # escalar que se recrea abajo solo puede representar uno de ellos (o
    # ninguno). Igual que el downgrade de f33c85dbb2f8, se comprueba en vez
    # de suponer, y se aborta ANTES de tocar el esquema si hay filas.
    conexion = op.get_bind()
    filas_procesos_fuente = conexion.execute(
        sa.text("SELECT count(*) FROM procesos_fuente")
    ).scalar_one()
    if filas_procesos_fuente:
        raise RuntimeError(
            f"No se puede revertir: procesos_fuente tiene {filas_procesos_fuente} "
            "fila(s). El escalar id_proceso_rama no puede representar una "
            "relación 1:N sin perder datos o inventar cuál proceso es 'el' "
            "proceso — no hay downgrade seguro mientras existan filas."
        )

    # --- 5 (inverso): recrear las tres columnas -------------------------------
    op.add_column(
        "expedientes", sa.Column("ultimo_consecutivo_visto", sa.Integer(), nullable=True)
    )
    op.add_column(
        "expedientes",
        sa.Column("fecha_ultima_consulta", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("expedientes", sa.Column("id_proceso_rama", sa.BigInteger(), nullable=True))

    # --- 3 (inverso): FK compuestas -> simples --------------------------------
    op.drop_constraint(
        "fk_expedientes_responsable_organizacion", "expedientes", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_expedientes_responsable_usuario_id_usuarios",
        "expedientes",
        "usuarios",
        ["responsable_usuario_id"],
        ["id"],
    )

    op.drop_constraint("fk_partes_expediente_organizacion", "partes", type_="foreignkey")
    op.create_foreign_key(
        "partes_expediente_id_fkey", "partes", "expedientes", ["expediente_id"], ["id"]
    )

    # --- 2 (inverso): tabla procesos_fuente -----------------------------------
    op.drop_index(op.f("ix_procesos_fuente_expediente_id"), table_name="procesos_fuente")
    op.drop_index(op.f("ix_procesos_fuente_organizacion_id"), table_name="procesos_fuente")
    op.drop_table("procesos_fuente")

    # --- 1 (inverso): UNIQUE (organizacion_id, id) ----------------------------
    op.drop_constraint("uq_expedientes_organizacion_id", "expedientes", type_="unique")
    op.drop_constraint("uq_usuarios_organizacion_id", "usuarios", type_="unique")
