"""Esquemas de `/v1/expedientes`."""
import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.models.expediente import Seguimiento, TipoIdentificador, TipoProceso

_PATRON_RADICADO_UNIFICADO = re.compile(r"^\d{23}$")


def _validar_identificador(tipo_identificador: TipoIdentificador, identificador: str) -> None:
    """La CHECK de 23 dígitos (B.1) se aplica solo a `radicado_unificado` —
    aquí y también a nivel de base de datos (`ck_expedientes_identificador_...`
    en la migración), la misma validación en dos capas que ya seguía el
    `radicado` original."""
    if tipo_identificador == TipoIdentificador.RADICADO_UNIFICADO and not _PATRON_RADICADO_UNIFICADO.fullmatch(
        identificador
    ):
        raise ValueError(
            "Con tipo_identificador='radicado_unificado' el identificador debe "
            "tener exactamente 23 dígitos"
        )


class ExpedienteCrear(BaseModel):
    identificador: str = Field(min_length=1, max_length=255)
    tipo_identificador: TipoIdentificador
    seguimiento: Seguimiento
    juzgado: str | None = Field(default=None, max_length=255)
    despacho: str | None = Field(default=None, max_length=255)
    partes: str | None = Field(default=None, max_length=10_000)
    tipo_proceso: TipoProceso
    ultima_actuacion_al_importar: str | None = Field(default=None, max_length=10_000)
    responsable_usuario_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _validar(self) -> "ExpedienteCrear":
        _validar_identificador(self.tipo_identificador, self.identificador)
        return self


class ExpedienteActualizar(BaseModel):
    """Todos los campos opcionales: PATCH solo toca lo que llega en el cuerpo
    (`exclude_unset` en `app/services/expedientes.py`)."""

    identificador: str | None = Field(default=None, min_length=1, max_length=255)
    tipo_identificador: TipoIdentificador | None = None
    seguimiento: Seguimiento | None = None
    juzgado: str | None = Field(default=None, max_length=255)
    despacho: str | None = Field(default=None, max_length=255)
    partes: str | None = Field(default=None, max_length=10_000)
    tipo_proceso: TipoProceso | None = None
    ultima_actuacion_al_importar: str | None = Field(default=None, max_length=10_000)
    responsable_usuario_id: uuid.UUID | None = None
    id_proceso_rama: int | None = None
    fecha_ultima_consulta: datetime | None = None
    ultimo_consecutivo_visto: int | None = None

    @model_validator(mode="after")
    def _validar(self) -> "ExpedienteActualizar":
        # Solo se puede validar la combinación cuando el PATCH trae los dos
        # campos a la vez: con uno solo no hay forma de saber aquí el valor
        # vigente del otro (vive en la fila que no se ha leído todavía). La
        # CHECK de la base de datos sigue cerrando esa vía igual que con
        # `radicado` antes de B.1.
        campos = self.model_fields_set
        if "tipo_identificador" in campos and "identificador" in campos:
            if self.tipo_identificador is not None and self.identificador is not None:
                _validar_identificador(self.tipo_identificador, self.identificador)
        return self


class ExpedienteResponse(BaseModel):
    id: uuid.UUID
    organizacion_id: uuid.UUID
    identificador: str
    tipo_identificador: TipoIdentificador
    seguimiento: Seguimiento
    juzgado: str | None
    despacho: str | None
    partes: str | None
    tipo_proceso: TipoProceso
    ultima_actuacion_al_importar: str | None
    activo: bool
    creado_en: datetime
    id_proceso_rama: int | None
    fecha_ultima_consulta: datetime | None
    ultimo_consecutivo_visto: int | None
    responsable_usuario_id: uuid.UUID | None

    model_config = {"from_attributes": True}


class ExpedienteListaResponse(BaseModel):
    items: list[ExpedienteResponse]
    total: int
