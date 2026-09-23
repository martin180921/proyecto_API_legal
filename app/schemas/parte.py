"""Esquema de `Parte` (A.2.2), la tabla estructurada de partes procesales.
Solo lectura desde la API (C.5, Bloque C): hoy la escribe
`scripts/importar_excel.py`, mañana el conector — nunca el cliente, por eso
no hay `ParteCrear` ni `ParteActualizar`, mismo criterio que
`ProcesoFuenteResponse`."""
import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.parte import OrigenParte


class ParteResponse(BaseModel):
    id: uuid.UUID
    expediente_id: uuid.UUID
    tipo: str
    nombre: str
    identificacion: str | None
    origen: OrigenParte
    creado_en: datetime

    model_config = {"from_attributes": True}
