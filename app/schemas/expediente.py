"""Esquemas de `/v1/expedientes`."""
import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.expediente import TipoProceso

_PATRON_RADICADO = re.compile(r"^\d{23}$")


def _validar_radicado(valor: str) -> str:
    if not _PATRON_RADICADO.fullmatch(valor):
        raise ValueError("El radicado debe tener exactamente 23 dígitos")
    return valor


class ExpedienteCrear(BaseModel):
    radicado: str = Field(min_length=23, max_length=23)
    juzgado: str | None = Field(default=None, max_length=255)
    despacho: str | None = Field(default=None, max_length=255)
    partes: str | None = Field(default=None, max_length=10_000)
    tipo_proceso: TipoProceso
    ultima_actuacion_conocida: str | None = Field(default=None, max_length=10_000)

    @field_validator("radicado")
    @classmethod
    def _radicado_valido(cls, valor: str) -> str:
        return _validar_radicado(valor)


class ExpedienteActualizar(BaseModel):
    """Todos los campos opcionales: PATCH solo toca lo que llega en el cuerpo
    (`exclude_unset` en `app/services/expedientes.py`)."""

    radicado: str | None = Field(default=None, min_length=23, max_length=23)
    juzgado: str | None = Field(default=None, max_length=255)
    despacho: str | None = Field(default=None, max_length=255)
    partes: str | None = Field(default=None, max_length=10_000)
    tipo_proceso: TipoProceso | None = None
    ultima_actuacion_conocida: str | None = Field(default=None, max_length=10_000)

    @field_validator("radicado")
    @classmethod
    def _radicado_valido(cls, valor: str | None) -> str | None:
        if valor is None:
            return None
        return _validar_radicado(valor)


class ExpedienteResponse(BaseModel):
    id: uuid.UUID
    organizacion_id: uuid.UUID
    radicado: str
    juzgado: str | None
    despacho: str | None
    partes: str | None
    tipo_proceso: TipoProceso
    ultima_actuacion_conocida: str | None
    activo: bool
    creado_en: datetime

    model_config = {"from_attributes": True}


class ExpedienteListaResponse(BaseModel):
    items: list[ExpedienteResponse]
    total: int
