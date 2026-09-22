"""Puente entre la sesión JWT ya construida (`app/core/security.py`) y
`app/web`: el mismo token, transportado en una cookie httpOnly en vez del
header `Authorization: Bearer` — un formulario HTML no manda ese header solo.

Decisión tomada con Martin el 2026-08-15 (no había nada escrito en la bóveda
al respecto): reusar el JWT vía cookie en vez de un sistema de sesión de
servidor aparte, para no duplicar lo que `security.py` ya resuelve.

`NoAutenticadoWeb` en vez de la `HTTPException` que usa `usuario_actual`: una
API responde 401 con JSON; una página debe redirigir a `/login`, no enseñar
JSON crudo. El manejador está en `app/main.py`.

`actor_verificado_desde_cookie` (A.1.3, Bloque A3, 2026-08-21) reutiliza
`actor_valido_y_activo` de `app/core/security.py` en vez de repetir el mismo
SELECT: la lección de A.1.1 fue justo que un núcleo compartido extraído a
medias reaparece duplicado en el borde. Desde A5.1 (2026-09-22, decisión de
Martin) también protege las rutas de solo lectura, no solo el alta de
expediente: `actor_desde_cookie` sin verificar queda como el paso intermedio
del que depende, no como dependencia directa de ninguna ruta.
"""
import uuid

import jwt
from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.security import ALGORITMO_JWT, EXPIRACION_TOKEN, ActorActual, actor_valido_y_activo

NOMBRE_COOKIE = "sesion"


class NoAutenticadoWeb(Exception):
    """Sin cookie, cookie inválida o expirada. Ver el manejador en `app/main.py`."""


def actor_desde_cookie(request: Request) -> ActorActual:
    token = request.cookies.get(NOMBRE_COOKIE)
    if token is None:
        raise NoAutenticadoWeb()
    try:
        claims = jwt.decode(token, settings.secret_key, algorithms=[ALGORITMO_JWT])
        return ActorActual(
            usuario_id=uuid.UUID(claims["sub"]),
            organizacion_id=uuid.UUID(claims["org"]),
        )
    except (jwt.PyJWTError, KeyError, ValueError) as error:
        raise NoAutenticadoWeb() from error


def actor_verificado_desde_cookie(
    actor: ActorActual = Depends(actor_desde_cookie),
    db: Session = Depends(get_db),
) -> ActorActual:
    if not actor_valido_y_activo(db, actor):
        raise NoAutenticadoWeb()
    return actor


def poner_cookie_sesion(response, token: str) -> None:
    """`secure` solo en producción: en local (HTTP, sin TLS) el navegador
    descartaría una cookie `secure` y nadie podría loguearse — mismo criterio
    de entorno que ya usa `ip_cliente` en `app/core/red.py`."""
    response.set_cookie(
        NOMBRE_COOKIE,
        token,
        max_age=int(EXPIRACION_TOKEN.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=settings.app_env == "production",
    )


def borrar_cookie_sesion(response) -> None:
    response.delete_cookie(NOMBRE_COOKIE)
