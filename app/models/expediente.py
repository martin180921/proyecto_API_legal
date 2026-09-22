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
(A.2.1) vivieron aquí como escalares hasta la migración de B.1-bis (A5.3,
2026-09-22): la revisión senior de P4 (C.1) encontró que un radicado puede
devolver varios `idProceso`, y que un proceso remitido a otro despacho
continúa bajo uno distinto — un escalar por expediente no podía representarlo.
El estado del motor vive ahora en `app/models/proceso_fuente.py::ProcesoFuente`
(relación 1:N, expuesta en `Expediente.procesos`, solo lectura desde la API —
R.4). Ver [[Relación expediente ↔ proceso de la fuente — B.1-bis]] en la
bóveda.

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

from sqlalchemy import (
    Boolean,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
        # Requisito de toda FK compuesta que apunte a `expedientes` desde una
        # tabla hija con tenancy propio (`partes`, `procesos_fuente`, R.3).
        UniqueConstraint("organizacion_id", "id", name="uq_expedientes_organizacion_id"),
        ForeignKeyConstraint(
            ["organizacion_id", "responsable_usuario_id"],
            ["usuarios.organizacion_id", "usuarios.id"],
            name="fk_expedientes_responsable_organizacion",
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

    responsable_usuario_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)

    # viewonly: la API nunca escribe aquí — lo hace el motor sobre
    # `ProcesoFuente` directamente (fuera de esta sesión). `foreign()` marca
    # el lado FK porque el join es compuesto (organizacion_id + expediente_id),
    # no la columna simple que `relationship()` infiere por defecto.
    procesos: Mapped[list["ProcesoFuente"]] = relationship(  # noqa: F821
        "ProcesoFuente",
        primaryjoin=(
            "and_(Expediente.id == foreign(ProcesoFuente.expediente_id), "
            "Expediente.organizacion_id == ProcesoFuente.organizacion_id)"
        ),
        viewonly=True,
        order_by="ProcesoFuente.creado_en",
    )
