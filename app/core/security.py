"""Hash de contraseñas, JWT de sesión y resolución del actor autenticado (T4).

Parámetros fijados por Martin el 2026-08-05, no elegidos por el agente de
código (Plan técnico por fases, bóveda): JWT **HS256**, claims mínimos
(`sub`, `org`, `exp`), expiración **8 horas, sin refresh** en F0.

`ActorActual` y `usuario_actual` están separados a propósito de "obtener un
`Usuario` de la base de datos": la dependencia se diseña como *actor actual*
para que, en el futuro, una API key pueda resolver el mismo `ActorActual`
sin sesión de base de datos de por medio. Aquí solo se deja el hueco — la
única implementación hoy es sesión JWT.
"""
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext

from app.core.config import settings

_contexto_contrasena = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITMO_JWT = "HS256"
EXPIRACION_TOKEN = timedelta(hours=8)

_bearer = HTTPBearer(auto_error=False)


def hash_contrasena(contrasena: str) -> str:
    return _contexto_contrasena.hash(contrasena)


def verificar_contrasena(contrasena: str, contrasena_hash: str) -> bool:
    return _contexto_contrasena.verify(contrasena, contrasena_hash)


# Señuelo calculado una vez al importar el módulo, sobre un valor aleatorio —
# nunca una contraseña real ni un literal del repositorio. Cuesta un bcrypt
# (~200ms) en el arranque del proceso; es el precio de que el señuelo esté
# listo antes de la primera petición, en vez de en la primera llamada con
# `contrasena_hash=None` (lo que haría lento justo ese primer intento y
# ninguno de los siguientes, un comportamiento más raro de depurar que un
# arranque fijo un poco más lento).
_HASH_SENUELO = hash_contrasena(secrets.token_urlsafe(32))


def verificar_o_quemar_tiempo(contrasena: str, contrasena_hash: str | None) -> bool:
    """Siempre corre bcrypt. Con `contrasena_hash=None` corre contra el
    señuelo y devuelve False: así el coste de un usuario u organización
    inexistente es el mismo que el de una contraseña mala, y el tiempo de
    respuesta deja de decir cuál de los tres casos fue.

    Cierra A.1.2: sin esto, un slug inexistente se rechaza con un SELECT
    (~1ms), un email inexistente con dos (~2ms), y una contraseña mala corre
    bcrypt (~100-300ms) — una diferencia de dos órdenes de magnitud, medible
    desde cualquier cliente, contra slugs que además son adivinables
    (`_slugify` los deriva del nombre del bufete)."""
    if contrasena_hash is None:
        verificar_contrasena(contrasena, _HASH_SENUELO)
        return False
    return verificar_contrasena(contrasena, contrasena_hash)


def crear_token_sesion(usuario_id: uuid.UUID, organizacion_id: uuid.UUID) -> str:
    ahora = datetime.now(timezone.utc)
    claims = {
        "sub": str(usuario_id),
        "org": str(organizacion_id),
        "exp": ahora + EXPIRACION_TOKEN,
    }
    return jwt.encode(claims, settings.secret_key, algorithm=ALGORITMO_JWT)


@dataclass(frozen=True)
class ActorActual:
    """Quién hace la petición, sin importar cómo se autenticó. Hoy solo lo
    produce `usuario_actual` a partir de un JWT de sesión; el hueco para que
    una API key produzca el mismo objeto queda abierto para más adelante."""

    usuario_id: uuid.UUID
    organizacion_id: uuid.UUID


def usuario_actual(
    credenciales: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> ActorActual:
    if credenciales is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado"
        )
    try:
        claims = jwt.decode(
            credenciales.credentials, settings.secret_key, algorithms=[ALGORITMO_JWT]
        )
        return ActorActual(
            usuario_id=uuid.UUID(claims["sub"]),
            organizacion_id=uuid.UUID(claims["org"]),
        )
    except (jwt.PyJWTError, KeyError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido o expirado"
        ) from error
