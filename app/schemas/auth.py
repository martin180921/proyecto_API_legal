"""Esquemas de `/v1/auth`.

`email` se tipa como `str`, no `EmailStr`: `EmailStr` exige el extra
`email-validator`, que no está en la lista de dependencias que fija el plan
para T4 (`passlib[bcrypt]`, `pyjwt`). Añadir una dependencia no pedida es la
clase de decisión silenciosa que las reglas de trabajo piden evitar — se deja
anotado aquí en vez de resolverlo de paso.
"""
import uuid

from pydantic import BaseModel, Field


class RegistroRequest(BaseModel):
    nombre_organizacion: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=255)
    contrasena: str = Field(min_length=8, max_length=72)


class RegistroResponse(BaseModel):
    organizacion_id: uuid.UUID
    organizacion_slug: str
    usuario_id: uuid.UUID
    email: str


class LoginRequest(BaseModel):
    organizacion: str = Field(min_length=1, max_length=255, description="Slug de la organización")
    email: str = Field(min_length=3, max_length=255)
    contrasena: str = Field(min_length=1, max_length=72)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expira_en_segundos: int


class YoResponse(BaseModel):
    usuario_id: uuid.UUID
    organizacion_id: uuid.UUID
    email: str
