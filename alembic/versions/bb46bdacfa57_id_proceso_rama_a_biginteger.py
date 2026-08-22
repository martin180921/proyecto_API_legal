"""id_proceso_rama a BigInteger (revisión P4, 2026-08-22)

`id_proceso_rama` nació como Integer (int32) en f33c85dbb2f8, pero el spike de
P4 documenta idRegActuacion=2694826740 (> 2^31-1) en la misma API de la Rama
Judicial: idProceso puede superar int32 y el primer UPDATE del conector habría
reventado. Migración nueva y no edición de f33c85dbb2f8 porque esa ya está
aplicada en Railway. La columna está toda en NULL (la llena el conector, que
no existe todavía), así que el alter y su downgrade son triviales, sin
conversión de datos. `ultimo_consecutivo_visto` se queda en Integer:
consActuacion es un consecutivo pequeño por expediente.

Revision ID: bb46bdacfa57
Revises: f33c85dbb2f8
Create Date: 2026-08-22 00:46:59.522981

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bb46bdacfa57'
down_revision: Union[str, Sequence[str], None] = 'f33c85dbb2f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "expedientes",
        "id_proceso_rama",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "expedientes",
        "id_proceso_rama",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
    )
