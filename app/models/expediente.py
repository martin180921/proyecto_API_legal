"""Expediente judicial. Pertenece a una organización (TenantMixin).

`identificador` + `tipo_identificador` sustituyen a `radicado` desde B.1
([[Identificador y seguimiento manual de Expediente — B.1]], bóveda,
2026-08-20): el radicado unificado de 23 dígitos es solo uno de los cuatro
casos reales del inventario de Juan Diego — hay radicados anteriores a la
unificación, demandas sin radicar todavía, y expedientes de responsabilidad
fiscal ante Contraloría sin radicado de Rama Judicial. La `CHECK` de 23
dígitos numéricos se aplica solo cuando `tipo_identificador =
'radicado_unificado'` (ver la migración).

`seguimiento` separa dos decisiones que antes eran una sola: que un
expediente **exista** en la plataforma y que la plataforma pueda
**consultarlo automáticamente**. Solo los expedientes `automatico` entran en
el ciclo del cron; los `manual` se ven en la misma lista, con una marca clara
del tipo, y el abogado los revisa a mano.

`tipo_proceso` se limita a civil | administrativo — los expedientes de
responsabilidad fiscal ante Contraloría entran con `tipo_identificador =
'expediente_contraloria'` y `seguimiento = 'manual'`, no como un tercer
`tipo_proceso`.

`id_proceso_rama`, `fecha_ultima_consulta` y `ultimo_consecutivo_visto`
(A.2.1) quedan preparados para `app/connectors/rama_judicial.py` (fuera de
esta sesión): el spike de P4 encontró que el conector necesita tres llamadas
encadenadas por expediente para llegar a las actuaciones, y `idProceso` es la
clave de las dos siguientes — guardarlo evita repetir la búsqueda por
radicado cada mañana. `ultimo_consecutivo_visto` es el `consActuacion` del
spike: compara por entero, no por fecha, que es frágil porque la Rama
Judicial registra actuaciones con fecha anterior a la de publicación.

`ultima_actuacion_al_importar` (A.2.3, antes `ultima_actuacion_conocida`) es
un dato histórico de la migración desde el Excel: no se actualiza después de
importarlo, salvo por un `PATCH` de corrección manual de datos de
importación (el mismo camino que ya corrigió el `juzgado` faltante el
2026-08-16). Cuando exista `app/models/actuacion.py` (Etapa Procesamiento), el
hecho vivo será la última fila de esa tabla, no esta columna — «un hecho, un
sitio».

`responsable_usuario_id` (A.2.4) es el abogado a avisar por correo (regla 7
de Juan Diego); nullable porque un expediente puede no tener responsable
asignado todavía.

`juzgado`, `despacho`, `partes` son opcionales: un expediente recién dado de
alta puede no tener todavía todos los datos que sí trae el Excel de Juan
Diego para procesos ya en curso. `partes` sigue siendo el texto libre de
importación — ver `app/models/parte.py` para la tabla estructurada que
alimentará el conector.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TenantMixin


class TipoProceso(str, enum.Enum):
    CIVIL = "civil"
    ADMINISTRATIVO = "administrativo"


class TipoIdentificador(str, enum.Enum):
    RADICADO_UNIFICADO = "radicado_unificado"
    RADICADO_ANTERIOR = "radicado_anterior"
    SIN_RADICAR = "sin_radicar"
    EXPEDIENTE_CONTRALORIA = "expediente_contraloria"


class Seguimiento(str, enum.Enum):
    AUTOMATICO = "automatico"
    MANUAL = "manual"


class Expediente(Base, TenantMixin):
    __tablename__ = "expedientes"

    __table_args__ = (
        UniqueConstraint(
            "organizacion_id", "identificador", name="uq_expedientes_organizacion_identificador"
        ),
    )

    identificador: Mapped[str] = mapped_column(String(255), nullable=False)
    tipo_identificador: Mapped[TipoIdentificador] = mapped_column(
        SAEnum(
            TipoIdentificador,
            name="tipo_identificador",
            native_enum=False,
            length=30,
            create_constraint=False,
            values_callable=lambda enum_cls: [miembro.value for miembro in enum_cls],
        ),
        nullable=False,
    )
    seguimiento: Mapped[Seguimiento] = mapped_column(
        SAEnum(
            Seguimiento,
            name="seguimiento",
            native_enum=False,
            length=20,
            create_constraint=False,
            values_callable=lambda enum_cls: [miembro.value for miembro in enum_cls],
        ),
        nullable=False,
    )
    juzgado: Mapped[str | None] = mapped_column(String(255), nullable=True)
    despacho: Mapped[str | None] = mapped_column(String(255), nullable=True)
    partes: Mapped[str | None] = mapped_column(Text, nullable=True)
    tipo_proceso: Mapped[TipoProceso] = mapped_column(
        SAEnum(
            TipoProceso,
            name="tipo_proceso",
            native_enum=False,
            length=20,
            create_constraint=False,
            values_callable=lambda enum_cls: [miembro.value for miembro in enum_cls],
        ),
        nullable=False,
    )
    ultima_actuacion_al_importar: Mapped[str | None] = mapped_column(Text, nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    id_proceso_rama: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fecha_ultima_consulta: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ultimo_consecutivo_visto: Mapped[int | None] = mapped_column(Integer, nullable=True)

    responsable_usuario_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("usuarios.id"), nullable=True
    )
