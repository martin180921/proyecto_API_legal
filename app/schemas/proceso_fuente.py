"""Esquema de `ProcesoFuente` (B.1-bis, A5.3, 2026-09-22). Solo lectura desde
la API: lo escribe el motor (`app/connectors/`, `app/services/revisor.py`,
fuera de esta sesión), nunca el cliente — por eso no hay `ProcesoFuenteCrear`
ni `ProcesoFuenteActualizar` (R.4)."""
import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.proceso_fuente import EstadoProcesoFuente, FuenteProceso


class ProcesoFuenteResponse(BaseModel):
    id: uuid.UUID
    expediente_id: uuid.UUID
    fuente: FuenteProceso
    id_externo: int
    id_conexion: int | None
    despacho: str | None
    departamento: str | None
    es_privado: bool
    ultima_actualizacion_fuente: datetime | None
    fecha_ultima_consulta: datetime | None
    estado: EstadoProcesoFuente
    creado_en: datetime

    model_config = {"from_attributes": True}
