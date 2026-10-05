"""Registro de cada revisión que el motor hace de un expediente (Etapa
Procesamiento; reglas 9 y 10 de Juan Diego — la `x` diaria del Excel, hecha
sistema).

**Una `Revision` por expediente y fuente en cada corrida, siempre**, también
cuando la fuente falla. Cuatro resultados, no dos (condición de entrada 3 del
spike P4, B.2 de [[2026-08-16 Revisión profunda — código y dominio jurídico]]):

- `con_novedad`: hay actuaciones nuevas.
- `sin_novedad`: la fuente respondió y no hay nada nuevo.
- `no_verificado`: la fuente no respondió, o respondió con otra forma. **No es
  `sin_novedad`**: registrar así un día en que la fuente falló es afirmar una
  diligencia que no hubo.
- `no_encontrado`: la fuente respondió que no conoce el identificador.

Es un registro de solo añadir: el motor nunca actualiza una fila, escribe otra.

`corrida_id` agrupa las revisiones de una misma ejecución del job — es lo que
permitirá a `GET /v1/estado-fuentes` decir «última corrida: X no verificados».
Nullable porque una revisión puede nacer fuera del job (a mano, desde la API).
`detalle` guarda el motivo corto de un `no_verificado`; el JSON crudo de lo
nuevo vive en `Actuacion.crudo`, no aquí.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TenantMixin
from app.models.proceso_fuente import FuenteProceso


class ResultadoRevision(str, enum.Enum):
    CON_NOVEDAD = "con_novedad"
    SIN_NOVEDAD = "sin_novedad"
    NO_VERIFICADO = "no_verificado"
    NO_ENCONTRADO = "no_encontrado"


class Revision(Base, TenantMixin):
    __tablename__ = "revisiones"

    __table_args__ = (
        # Requisito de la FK compuesta desde `actuaciones` (mismo patrón que
        # `expedientes` y `procesos_fuente`, R.3).
        UniqueConstraint("organizacion_id", "id", name="uq_revisiones_organizacion_id"),
        ForeignKeyConstraint(
            ["organizacion_id", "expediente_id"],
            ["expedientes.organizacion_id", "expedientes.id"],
            name="fk_revisiones_expediente_organizacion",
        ),
    )

    expediente_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    fuente: Mapped[FuenteProceso] = mapped_column(
        SAEnum(
            FuenteProceso,
            name="fuente_proceso",
            native_enum=False,
            length=30,
            create_constraint=False,
            values_callable=lambda enum_cls: [miembro.value for miembro in enum_cls],
        ),
        nullable=False,
    )
    resultado: Mapped[ResultadoRevision] = mapped_column(
        SAEnum(
            ResultadoRevision,
            name="resultado_revision",
            native_enum=False,
            length=20,
            create_constraint=False,
            values_callable=lambda enum_cls: [miembro.value for miembro in enum_cls],
        ),
        nullable=False,
    )
    # Reloj de la base de datos, como `creado_en`: el momento de la revisión no
    # depende del reloj del contenedor.
    revisado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    corrida_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    detalle: Mapped[str | None] = mapped_column(String(500), nullable=True)
