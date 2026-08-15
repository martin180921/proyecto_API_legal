"""Núcleo del login, compartido entre `/v1/auth/login` (JSON, header
`Authorization: Bearer`) y `app/web` (cookie httpOnly con el mismo JWT).

Extraído de `app/api/v1/auth.py` al construir `app/web/` (Etapa Entrada,
S3–4): la alternativa era reimplementar rate-limit + verificación de
contraseña + auditoría una segunda vez para la superficie web, y duplicar
código security-sensitive es exactamente el tipo de divergencia que este
proyecto no se puede permitir en auth. Mismo comportamiento que antes, solo
movido — no cambia rate-limit, mensajes ni eventos de auditoría.
"""
import uuid
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.rate_limit import limite_superado, limpiar, marcar_auditado, registrar_intento
from app.core.security import crear_token_sesion, verificar_contrasena
from app.models.organizacion import Organizacion
from app.models.usuario import Usuario
from app.services import auditoria


@dataclass(frozen=True)
class ResultadoLogin:
    token: str
    usuario_id: uuid.UUID
    organizacion_id: uuid.UUID


def intentar_login(
    db: Session, organizacion_slug: str, email: str, contrasena: str, ip: str
) -> ResultadoLogin:
    """Levanta `HTTPException` (401 o 429) igual que hacía el endpoint
    original: cada llamador decide qué hacer con ella (el JSON la deja subir
    tal cual, la web la convierte en un formulario con error)."""
    organizacion = db.query(Organizacion).filter_by(slug=organizacion_slug).one_or_none()
    if organizacion is None:
        # Sin organización no hay `organizacion_id` para el audit log ni para
        # el contador de rate-limit por-organización. Se rechaza sin dejar
        # rastro, igual que una contraseña incorrecta.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas")

    clave_usuario = f"login:org:{organizacion.id}:email:{email}"
    clave_ip = f"login:org:{organizacion.id}:ip:{ip}"

    superadas = [clave for clave in (clave_usuario, clave_ip) if limite_superado(clave)]
    if superadas:
        # Se audita solo la TRANSICIÓN, no cada petición bloqueada — ver
        # `app/api/v1/auth.py` para el razonamiento completo.
        nuevas = [clave for clave in superadas if marcar_auditado(clave)]
        if nuevas:
            auditoria.registrar(
                db,
                organizacion_id=organizacion.id,
                accion="rate_limit_superado",
                entidad="login_fallido",
                detalle={"ip": ip, "email": email},
            )
            db.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos fallidos. Intenta de nuevo en unos minutos.",
        )

    usuario = (
        db.query(Usuario).filter_by(organizacion_id=organizacion.id, email=email).one_or_none()
    )

    if usuario is None or not verificar_contrasena(contrasena, usuario.contrasena_hash):
        registrar_intento(clave_usuario)
        registrar_intento(clave_ip)
        auditoria.registrar(
            db,
            organizacion_id=organizacion.id,
            accion="login_fallido",
            entidad="login_fallido",
            usuario_id=usuario.id if usuario is not None else None,
            detalle={"ip": ip, "email": email},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas")

    # Un acierto borra el historial de fallos.
    limpiar(clave_usuario)
    limpiar(clave_ip)

    auditoria.registrar(
        db,
        organizacion_id=organizacion.id,
        accion="login",
        entidad="sesion",
        entidad_id=None,
        usuario_id=usuario.id,
        detalle={"ip": ip},
    )
    db.commit()

    token = crear_token_sesion(usuario.id, organizacion.id)
    return ResultadoLogin(token=token, usuario_id=usuario.id, organizacion_id=organizacion.id)
