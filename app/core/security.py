"""Hash de contraseñas, JWT de sesión y resolución del actor autenticado (T4).

Parámetros fijados por Martin el 2026-08-05, no elegidos por el agente de
código (Plan técnico por fases, bóveda): JWT **HS256**, claims mínimos
(`sub`, `org`, `exp`), expiración **8 horas, sin refresh** en F0.

`ActorActual` y `usuario_actual` están separados a propósito de "obtener un
`Usuario` de la base de datos": la dependencia se diseña como *actor actual*
para que, en el futuro, una API key pueda resolver el mismo `ActorActual`
sin sesión de base de datos de por medio. Aquí solo se deja el hueco — la
única implementación hoy es sesión JWT.

`usuario_actual_verificado` (A.1.3, Bloque A3, 2026-08-21) es la variante que
sí toca la base: un SELECT por PK para comprobar que el usuario sigue
existiendo, pertenece a la organización del token y está `activo`. Sin esto,
revocarle el acceso a un usuario no corta su JWT hasta que expire (hasta 8
horas).

Hasta A5.1 se aplicaba solo a las rutas que **mutan** datos, y las de solo
lectura se quedaban con `usuario_actual` (sin SELECT extra), asumiendo que el
coste de que un token revocado siga *leyendo* unas horas era menor que el de
que siga *escribiendo*. Martin decidió el 2026-09-22 extenderlo también a
lectura (`GET /v1/expedientes`, la lista y el alta en `app/web`): un SELECT
por PK de más en cada lectura, a cambio de que desactivar a alguien le corte
el acceso de inmediato, no en hasta 8 horas.
"""
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db

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


def actor_valido_y_activo(db: Session, actor: ActorActual) -> bool:
    """SELECT por PK: el usuario del token existe, sigue en la misma
    organización y está `activo`. Import perezoso de `Usuario` para no atar
    `app.core.security` a `app.models` en tiempo de import — el resto de este
    módulo no depende de ningún modelo."""
    from app.models.usuario import Usuario

    usuario = db.get(Usuario, actor.usuario_id)
    return (
        usuario is not None
        and usuario.organizacion_id == actor.organizacion_id
        and usuario.activo
    )


def usuario_actual_verificado(
    actor: ActorActual = Depends(usuario_actual),
    db: Session = Depends(get_db),
) -> ActorActual:
    """Variante de `usuario_actual` para rutas que mutan datos: revalida
    contra la base en vez de confiar a ciegas en los claims del JWT (A.1.3).
    Mismo 401 genérico que un token inválido, para no distinguir "token
    válido de usuario desactivado" de "token inválido"."""
    if not actor_valido_y_activo(db, actor):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido o expirado"
        )
    return actor
