"""Esquema de `GET /v1/estado-fuentes` (Etapa Procesamiento, P6): lo que
convierte un fallo silencioso del motor en uno visible."""
import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.proceso_fuente import FuenteProceso


class ConteoResultados(BaseModel):
    con_novedad: int = 0
    sin_novedad: int = 0
    no_verificado: int = 0
    no_encontrado: int = 0


class ExpedienteNoVerificado(BaseModel):
    expediente_id: uuid.UUID
    identificador: str
    fuente: FuenteProceso
    detalle: str | None
    revisado_en: datetime


class CorridaResumen(BaseModel):
    corrida_id: uuid.UUID
    # Primera y última revisión de esta organización en la corrida: sin
    # `terminada_en` fiable el SPA no puede distinguir «terminó» de «se cayó
    # a medias», así que se da el momento de la última revisión, no un estado.
    iniciada_en: datetime
    ultima_revision_en: datetime
    total: int
    resultados: ConteoResultados


class EstadoFuentesResponse(BaseModel):
    # `None` mientras el job no haya corrido nunca para esta organización.
    ultima_corrida: CorridaResumen | None
    # Los `no_verificado` de esa corrida, con su motivo; `total` cuenta todos,
    # `items` respeta `limit`/`offset`.
    no_verificados: list[ExpedienteNoVerificado]
    no_verificados_total: int
    limit: int
    offset: int
