"""Esquema de `Usuario` para el selector de responsable del SPA (C.5, Bloque
C). Solo lectura: el alta de usuario no es parte de esta API todavía
(`scripts/crear_organizacion.py` crea el primero; no hay endpoint de alta de
usuarios adicionales), así que no hay `UsuarioCrear`."""
import uuid

from pydantic import BaseModel


class UsuarioResponse(BaseModel):
    id: uuid.UUID
    nombre: str
    email: str
    activo: bool

    model_config = {"from_attributes": True}


class UsuarioListaResponse(BaseModel):
    items: list[UsuarioResponse]
