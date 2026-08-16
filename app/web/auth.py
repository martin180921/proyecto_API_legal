"""Puente entre la sesión JWT ya construida (`app/core/security.py`) y
`app/web`: el mismo token, transportado en una cookie httpOnly en vez del
header `Authorization: Bearer` — un formulario HTML no manda ese header solo.

Decisión tomada con Martin el 2026-08-15 (no había nada escrito en la bóveda
al respecto): reusar el JWT vía cookie en vez de un sistema de sesión de
servidor aparte, para no duplicar lo que `security.py` ya resuelve.

`NoAutenticadoWeb` en vez de la `HTTPException` que usa `usuario_actual`: una
API responde 401 con JSON; una página debe redirigir a `/login`, no enseñar
JSON crudo. El manejador está en `app/main.py`.
"""
import uuid

import jwt
from fastapi import Request

from app.core.config import settings
from app.core.security import ALGORITMO_JWT, EXPIRACION_TOKEN, ActorActual

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
