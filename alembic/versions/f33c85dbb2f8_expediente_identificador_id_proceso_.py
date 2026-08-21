"""expediente identificador, id_proceso_rama, partes, responsable, usuario activo (Bloque A3)

Agrupa los seis cambios de esquema del Bloque A3 (revisión del 2026-08-16,
apartados A.1.3, A.2.1, A.2.2, A.2.3, A.2.4 y B.1) en una sola revisión, tal
como pide la regla de trabajo del desarrollador único: son seis cambios que
se piensan y se despliegan como una unidad, y separarlos en migraciones
sueltas habría sido más riesgo, no menos, sobre todo después del conector
(cuando habrían sido migraciones con conversión de datos de verdad).

1. `Expediente.radicado` -> `identificador` + `tipo_identificador` +
   `seguimiento` (B.1). Backfill: los expedientes existentes son todos
   `radicado_unificado` / `automatico` — es lo único que podían ser bajo el
   esquema anterior.
2. `id_proceso_rama`, `fecha_ultima_consulta`, `ultimo_consecutivo_visto`
   (A.2.1). Nullable, sin backfill: los llena el conector, que no existe
   todavía.
3. `ultima_actuacion_conocida` -> `ultima_actuacion_al_importar` (A.2.3):
   simple rename, decisión (b) de la sesión — dato histórico de importación,
   no derivado.
4. Tabla `partes` (A.2.2): estructurada, con `organizacion_id` propio vía el
   mismo patrón de `TenantMixin` que el resto del proyecto.
5. `Expediente.responsable_usuario_id` + `Usuario.nombre` (A.2.4). `nombre`
   es NOT NULL con backfill desde la parte local del email: no hay forma de
   confirmar contra producción cuántos usuarios reales existen hoy sin
   nombre (fuera de alcance de esta sesión no tocar Railway), así que el
   backfill deja el esquema correcto sin importar el conteo real.
6. `Usuario.activo` (A.1.3): NOT NULL con `server_default true` para no
   fricción con los usuarios existentes; el default de servidor se retira
   después de sembrar, porque el default que gobierna las filas nuevas es el
   de la aplicación (`Usuario.activo`, `default=True` en el modelo).

Revision ID: f33c85dbb2f8
Revises: 83e6acf6b885
Create Date: 2026-08-21 18:05:58.947131

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f33c85dbb2f8'
down_revision: Union[str, Sequence[str], None] = '83e6acf6b885'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- 1. B.1: identificador / tipo_identificador / seguimiento ----------
    op.add_column("expedientes", sa.Column("identificador", sa.String(length=255), nullable=True))
    op.add_column(
        "expedientes", sa.Column("tipo_identificador", sa.String(length=30), nullable=True)
    )
    op.add_column("expedientes", sa.Column("seguimiento", sa.String(length=20), nullable=True))

    # Backfill: bajo el esquema anterior, todo expediente existente tenía
    # `radicado` de 23 dígitos validado por la CHECK que se retira más abajo
    # — así que todos son `radicado_unificado` / `automatico`.
    op.execute(
        "UPDATE expedientes SET identificador = radicado, "
        "tipo_identificador = 'radicado_unificado', seguimiento = 'automatico'"
    )

    op.alter_column("expedientes", "identificador", nullable=False)
    op.alter_column("expedientes", "tipo_identificador", nullable=False)
    op.alter_column("expedientes", "seguimiento", nullable=False)

    op.drop_constraint("uq_expedientes_organizacion_radicado", "expedientes", type_="unique")
    op.drop_constraint("ck_expedientes_radicado_23_digitos", "expedientes", type_="check")
    op.drop_column("expedientes", "radicado")

    op.create_unique_constraint(
        "uq_expedientes_organizacion_identificador",
        "expedientes",
        ["organizacion_id", "identificador"],
    )
    op.create_check_constraint(
        "ck_expedientes_tipo_identificador",
        "expedientes",
        "tipo_identificador IN ('radicado_unificado', 'radicado_anterior', 'sin_radicar', "
        "'expediente_contraloria')",
    )
    op.create_check_constraint(
        "ck_expedientes_seguimiento", "expedientes", "seguimiento IN ('automatico', 'manual')"
    )
    # La CHECK de 23 dígitos (B.1) se condiciona: solo se exige cuando
    # `tipo_identificador = 'radicado_unificado'`. Cualquier otro tipo puede
    # llevar el identificador que exista hoy (o ninguno confirmado todavía).
    op.create_check_constraint(
        "ck_expedientes_identificador_radicado_unificado_23_digitos",
        "expedientes",
        "tipo_identificador <> 'radicado_unificado' OR identificador ~ '^[0-9]{23}$'",
    )

    # --- 2. A.2.1: campos que preparan el conector -------------------------
    op.add_column("expedientes", sa.Column("id_proceso_rama", sa.Integer(), nullable=True))
    op.add_column(
        "expedientes",
        sa.Column("fecha_ultima_consulta", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "expedientes", sa.Column("ultimo_consecutivo_visto", sa.Integer(), nullable=True)
    )

    # --- 3. A.2.3: ultima_actuacion_conocida -> ultima_actuacion_al_importar
    op.alter_column(
        "expedientes", "ultima_actuacion_conocida", new_column_name="ultima_actuacion_al_importar"
    )

    # --- 4. A.2.2: tabla partes ---------------------------------------------
    op.create_table(
        "partes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "creado_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("organizacion_id", sa.Uuid(), nullable=False),
        sa.Column("expediente_id", sa.Uuid(), nullable=False),
        sa.Column("tipo", sa.String(length=100), nullable=False),
        sa.Column("nombre", sa.String(length=255), nullable=False),
        sa.Column("identificacion", sa.String(length=50), nullable=True),
        sa.Column("origen", sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organizacion_id"], ["organizaciones.id"]),
        sa.ForeignKeyConstraint(["expediente_id"], ["expedientes.id"]),
        sa.CheckConstraint("origen IN ('importacion', 'conector')", name="ck_partes_origen"),
    )
    op.create_index(op.f("ix_partes_organizacion_id"), "partes", ["organizacion_id"], unique=False)
    op.create_index(op.f("ix_partes_expediente_id"), "partes", ["expediente_id"], unique=False)

    # --- 5. A.2.4: responsable_usuario_id + Usuario.nombre ------------------
    op.add_column(
        "expedientes", sa.Column("responsable_usuario_id", sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        "fk_expedientes_responsable_usuario_id_usuarios",
        "expedientes",
        "usuarios",
        ["responsable_usuario_id"],
        ["id"],
    )

    op.add_column("usuarios", sa.Column("nombre", sa.String(length=255), nullable=True))
    # Backfill desde la parte local del email: no hay forma de confirmar
    # contra producción (fuera de alcance de esta sesión) cuántos usuarios
    # reales existen hoy sin nombre, así que se elige un valor que deja el
    # esquema correcto sin importar el conteo — se corrige después con
    # `PATCH`/edición de perfil (fuera de esta sesión) si hace falta.
    op.execute(
        "UPDATE usuarios SET nombre = split_part(email, '@', 1) WHERE nombre IS NULL"
    )
    op.alter_column("usuarios", "nombre", nullable=False)

    # --- 6. A.1.3: Usuario.activo --------------------------------------------
    op.add_column(
        "usuarios",
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    # El default de servidor solo hacía falta para sembrar las filas
    # existentes sin fricción; de aquí en adelante el default lo gobierna la
    # aplicación (`Usuario.activo`, `default=True` en el modelo).
    op.alter_column("usuarios", "activo", server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    # --- 6 y 5 (inverso): activo, responsable_usuario_id, nombre -----------
    op.drop_column("usuarios", "activo")

    op.drop_constraint(
        "fk_expedientes_responsable_usuario_id_usuarios", "expedientes", type_="foreignkey"
    )
    op.drop_column("expedientes", "responsable_usuario_id")

    # `nombre` no tiene un valor previo que restaurar — la columna no
    # existía — así que basta con quitarla.
    op.drop_column("usuarios", "nombre")

    # --- 4 (inverso): tabla partes ------------------------------------------
    op.drop_index(op.f("ix_partes_expediente_id"), table_name="partes")
    op.drop_index(op.f("ix_partes_organizacion_id"), table_name="partes")
    op.drop_table("partes")

    # --- 3 (inverso): rename de vuelta ---------------------------------------
    op.alter_column(
        "expedientes", "ultima_actuacion_al_importar", new_column_name="ultima_actuacion_conocida"
    )

    # --- 2 (inverso): columnas del conector -----------------------------------
    op.drop_column("expedientes", "ultimo_consecutivo_visto")
    op.drop_column("expedientes", "fecha_ultima_consulta")
    op.drop_column("expedientes", "id_proceso_rama")

    # --- 1 (inverso): identificador -> radicado ------------------------------
    # Primera migración del proyecto con backfill de datos: un downgrade que
    # no lo revierte deja el rollback a medias. Pero el backfill de B.1 no es
    # reversible sin pérdida si hay filas que el esquema anterior no podía
    # representar — exactamente el problema que B.1 vino a resolver. Un
    # `sin_radicar` o un `expediente_contraloria` no tiene ningún radicado de
    # 23 dígitos que reconstruir: forzarlo violaría la CHECK antigua o
    # inventaría un dato. La única salida honesta es negarse a bajar si existe
    # alguna fila así, en vez de silenciarla o corromper la CHECK de destino.
    conexion = op.get_bind()
    filas_no_convertibles = conexion.execute(
        sa.text(
            "SELECT count(*) FROM expedientes WHERE tipo_identificador <> 'radicado_unificado'"
        )
    ).scalar_one()
    if filas_no_convertibles:
        raise RuntimeError(
            f"No se puede revertir: hay {filas_no_convertibles} expediente(s) con "
            "tipo_identificador distinto de 'radicado_unificado' (sin_radicar, "
            "radicado_anterior o expediente_contraloria). El esquema anterior solo "
            "podía representar radicados unificados de 23 dígitos — exactamente el "
            "problema que B.1 resolvió — así que no hay downgrade seguro mientras "
            "existan. Archívalos o corrígelos a radicado_unificado antes de bajar, "
            "o acepta que este downgrade no es viable con estos datos."
        )

    op.drop_constraint(
        "ck_expedientes_identificador_radicado_unificado_23_digitos",
        "expedientes",
        type_="check",
    )
    op.drop_constraint("ck_expedientes_seguimiento", "expedientes", type_="check")
    op.drop_constraint("ck_expedientes_tipo_identificador", "expedientes", type_="check")
    op.drop_constraint(
        "uq_expedientes_organizacion_identificador", "expedientes", type_="unique"
    )

    op.add_column("expedientes", sa.Column("radicado", sa.String(length=23), nullable=True))
    op.execute("UPDATE expedientes SET radicado = identificador")
    op.alter_column("expedientes", "radicado", nullable=False)

    op.create_check_constraint(
        "ck_expedientes_radicado_23_digitos", "expedientes", "radicado ~ '^[0-9]{23}$'"
    )
    op.create_unique_constraint(
        "uq_expedientes_organizacion_radicado", "expedientes", ["organizacion_id", "radicado"]
    )

    op.drop_column("expedientes", "seguimiento")
    op.drop_column("expedientes", "tipo_identificador")
    op.drop_column("expedientes", "identificador")
