"""`/v1/auth` — sesión de usuario, con el hueco dejado para API keys futuras.

Parámetros fijados por Martin el 2026-08-05 (Plan técnico por fases, bóveda),
no elegidos aquí: JWT HS256, expiración 8h sin refresh, rate-limit de login
con contador simple (`app/core/rate_limit.py`) de 5 intentos por clave en 15
minutos, con evento de auditoría al superarlo. El login recibe organización
(slug) + email + contraseña como campos explícitos, no subdominio — decisión
directa de [[Email único por organización, no global]].

Sobre el rate-limit y el audit log: `eventos_auditoria.organizacion_id` es
NOT NULL ([[Multi-tenancy y audit log desde el día 1]]), así que un intento
de login contra un slug que no existe no puede dejar evento — no hay
organización a la que atribuirlo. Se responde 401 sin más, igual que con
credenciales inválidas: no se distingue "organización inexistente" de
"contraseña incorrecta" en la respuesta, para no revelar qué slugs existen.
"""
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.rate_limit import limite_superado, registrar_intento_fallido
from app.core.security import (
    EXPIRACION_TOKEN,
    ActorActual,
    crear_token_sesion,
    hash_contrasena,
    usuario_actual,
    verificar_contrasena,
)
from app.models.organizacion import Organizacion
from app.models.usuario import Usuario
from app.schemas.auth import (
    LoginRequest,
    RegistroRequest,
    RegistroResponse,
    TokenResponse,
    YoResponse,
)
from app.services import auditoria

router = APIRouter(prefix="/auth", tags=["auth"])


def _slugify(texto: str) -> str:
    slug = texto.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug or "org"


def _generar_slug_unico(db: Session, nombre: str) -> str:
    base = _slugify(nombre)
    slug = base
    while db.query(Organizacion).filter_by(slug=slug).one_or_none() is not None:
        slug = f"{base}-{secrets.token_hex(2)}"
    return slug


def _clave_ip(request: Request) -> str:
    return request.client.host if request.client else "desconocida"


@router.post("/registro", response_model=RegistroResponse, status_code=status.HTTP_201_CREATED)
def registro(payload: RegistroRequest, db: Session = Depends(get_db)) -> RegistroResponse:
    slug = _generar_slug_unico(db, payload.nombre_organizacion)
    organizacion = Organizacion(nombre=payload.nombre_organizacion, slug=slug)
    db.add(organizacion)
    db.flush()

    usuario = Usuario(
        organizacion_id=organizacion.id,
        email=payload.email,
        contrasena_hash=hash_contrasena(payload.contrasena),
    )
    db.add(usuario)
    db.flush()

    auditoria.registrar(
        db,
        organizacion_id=organizacion.id,
        accion="crear",
        entidad="organizacion",
        entidad_id=organizacion.id,
    )
    auditoria.registrar(
        db,
        organizacion_id=organizacion.id,
        accion="crear",
        entidad="usuario",
        entidad_id=usuario.id,
        usuario_id=usuario.id,
    )
    db.commit()

    return RegistroResponse(
        organizacion_id=organizacion.id,
        organizacion_slug=organizacion.slug,
        usuario_id=usuario.id,
        email=usuario.email,
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    organizacion = db.query(Organizacion).filter_by(slug=payload.organizacion).one_or_none()

    if organizacion is None:
        # Sin organización no hay `organizacion_id` para el audit log ni para
        # el contador de rate-limit por-organización. Se rechaza sin dejar
        # rastro, igual que una contraseña incorrecta — ver docstring.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas")

    clave_usuario = f"login:org:{organizacion.id}:email:{payload.email}"
    clave_ip = f"login:org:{organizacion.id}:ip:{_clave_ip(request)}"

    if limite_superado(clave_usuario) or limite_superado(clave_ip):
        auditoria.registrar(
            db,
            organizacion_id=organizacion.id,
            accion="rate_limit_superado",
            entidad="login_fallido",
            detalle={"ip": _clave_ip(request), "email": payload.email},
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos fallidos. Intenta de nuevo en unos minutos.",
        )

    usuario = (
        db.query(Usuario)
        .filter_by(organizacion_id=organizacion.id, email=payload.email)
        .one_or_none()
    )

    if usuario is None or not verificar_contrasena(payload.contrasena, usuario.contrasena_hash):
        registrar_intento_fallido(clave_usuario)
        registrar_intento_fallido(clave_ip)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas")

    token = crear_token_sesion(usuario.id, organizacion.id)
    return TokenResponse(
        access_token=token,
        expira_en_segundos=int(EXPIRACION_TOKEN.total_seconds()),
    )


@router.get("/yo", response_model=YoResponse)
def yo(actor: ActorActual = Depends(usuario_actual), db: Session = Depends(get_db)) -> YoResponse:
    usuario = db.get(Usuario, actor.usuario_id)
    if usuario is None or usuario.organizacion_id != actor.organizacion_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido o expirado")

    return YoResponse(
        usuario_id=usuario.id,
        organizacion_id=usuario.organizacion_id,
        email=usuario.email,
    )
