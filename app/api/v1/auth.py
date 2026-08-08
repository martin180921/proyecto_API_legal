"""`/v1/auth` — sesión de usuario, con el hueco dejado para API keys futuras.

Parámetros fijados por Martin el 2026-08-05 (Plan técnico por fases, bóveda),
no elegidos aquí: JWT HS256, expiración 8h sin refresh, rate-limit de login
con contador simple (`app/core/rate_limit.py`) de 5 intentos por clave en 15
minutos, con evento de auditoría al superarlo. El login recibe organización
(slug) + email + contraseña como campos explícitos, no subdominio — decisión
directa de [[Email único por organización, no global]].

Qué deja este módulo en el audit log
------------------------------------
| Qué pasa            | accion               | entidad        | usuario_id      |
|---------------------|----------------------|----------------|-----------------|
| Registro            | `crear`              | `organizacion` / `usuario` | el creado |
| Login correcto      | `login`              | `sesion`       | quien entra     |
| Contraseña mala     | `login_fallido`      | `login_fallido`| quien lo intenta |
| Email inexistente   | `login_fallido`      | `login_fallido`| NULL            |
| Rate-limit superado | `rate_limit_superado`| `login_fallido`| NULL            |

*Quién entró y cuándo* es el evento principal de una plataforma legal con un
audit log de posible valor probatorio, así que el login correcto deja rastro
igual que el fallido. En `detalle` va la IP (y el email en los fallidos, que
es lo que se estaba probando) — **nunca la contraseña ni el token**.

Sobre el rate-limit y el audit log: `eventos_auditoria.organizacion_id` es
NOT NULL ([[Multi-tenancy y audit log desde el día 1]]), así que un intento
de login contra un slug que no existe no puede dejar evento — no hay
organización a la que atribuirlo. Se responde 401 sin más, igual que con
credenciales inválidas: no se distingue "organización inexistente" de
"contraseña incorrecta" en la respuesta, para no revelar qué slugs existen.
"""
import ipaddress
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.rate_limit import limite_superado, marcar_auditado, registrar_intento
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


def _ip_cliente(request: Request) -> str:
    """La IP del cliente de verdad, no la del proxy que tiene delante.

    En Railway `request.client.host` devuelve la IP del *edge*, la misma para
    todo el tráfico. Con eso, la clave `login:org:<id>:ip:<ip>` se colapsa en
    **una sola por organización**: 5 fallos de cualquiera dejan fuera a toda la
    firma durante 15 minutos, y no filtran a ningún atacante. Una protección
    que se cree activa y no lo está es peor que no tenerla.

    EL SUPUESTO, que hay que revisar el día que cambie el despliegue: confiar
    en `X-Forwarded-For` **solo es válido porque en Railway todo el tráfico
    entra por el proxy**, que reescribe la cabecera. Si algún día se expone el
    puerto de la aplicación directamente, cualquier cliente puede falsificarla
    —y con ella saltarse el rate-limit o ensuciar el audit log— y esto deja de
    valer. Por eso solo se mira en `production`: en local y en CI no hay proxy
    delante, así que la cabecera solo podría venir de quien hace la petición.

    Se toma el **primer** valor: el proxy añade por la derecha, así que el de
    más a la izquierda es el cliente original.
    """
    directa = request.client.host if request.client else "desconocida"

    if settings.app_env != "production":
        return directa

    primero = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    try:
        # Validar además de recortar: si la cabecera falta o trae basura, se
        # cae a la IP directa en vez de meter texto arbitrario de la petición
        # en una clave de rate-limit y en el `detalle` del audit log.
        return str(ipaddress.ip_address(primero))
    except ValueError:
        return directa


@router.post("/registro", response_model=RegistroResponse, status_code=status.HTTP_201_CREATED)
def registro(
    payload: RegistroRequest, request: Request, db: Session = Depends(get_db)
) -> RegistroResponse:
    if not settings.registro_abierto:
        # 403 antes de tocar la base de datos y antes de bcrypt: con el
        # registro cerrado, esta petición no debe costar nada. El mensaje es
        # neutro a propósito — no dice si la instancia podría abrirse ni cómo.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El registro no está disponible en esta instancia.",
        )

    # Rate-limit por IP aunque el registro esté abierto: es barato y cubre el
    # día que se abra. Se cuenta ANTES de trabajar, porque lo que se limita es
    # el trabajo caro (bcrypt) y la creación de organizaciones, no el error.
    #
    # Este 429 no deja evento de auditoría, y no es un olvido:
    # `eventos_auditoria.organizacion_id` es NOT NULL y aquí todavía no hay
    # ninguna organización a la que atribuirlo — el mismo razonamiento que el
    # del slug inexistente en el login (ver docstring del módulo).
    clave_registro = f"registro:ip:{_ip_cliente(request)}"
    if limite_superado(clave_registro):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados registros desde esta dirección. Intenta de nuevo en unos minutos.",
        )
    registrar_intento(clave_registro)

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

    ip = _ip_cliente(request)
    clave_usuario = f"login:org:{organizacion.id}:email:{payload.email}"
    clave_ip = f"login:org:{organizacion.id}:ip:{ip}"

    superadas = [clave for clave in (clave_usuario, clave_ip) if limite_superado(clave)]
    if superadas:
        # Se audita solo la TRANSICIÓN: la primera vez que una clave cruza el
        # umbral dentro de la ventana. Antes se escribía una fila por cada
        # petición bloqueada, así que quien insistiera generaba escrituras
        # ilimitadas en la única tabla que por diseño no se puede borrar — el
        # rate-limit no detenía la escritura, la provocaba.
        #
        # La lista se materializa a propósito, en vez de un `any(...)` que
        # cortocircuitaría: las dos claves tienen que quedar marcadas, o la
        # segunda acabaría auditándose en una petición posterior.
        nuevas = [clave for clave in superadas if marcar_auditado(clave)]
        if nuevas:
            auditoria.registrar(
                db,
                organizacion_id=organizacion.id,
                accion="rate_limit_superado",
                entidad="login_fallido",
                detalle={"ip": ip, "email": payload.email},
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
        registrar_intento(clave_usuario)
        registrar_intento(clave_ip)
        auditoria.registrar(
            db,
            organizacion_id=organizacion.id,
            accion="login_fallido",
            entidad="login_fallido",
            # Si el email no existe en esta organización no hay a quién
            # atribuirlo, pero el intento sigue siendo el dato interesante:
            # alguien probando correos contra una firma concreta.
            usuario_id=usuario.id if usuario is not None else None,
            detalle={"ip": ip, "email": payload.email},
        )
        # El 401 también tiene que persistir su evento: sin este commit, la
        # excepción de abajo se lleva por delante la transacción y el intento
        # fallido no queda registrado en ninguna parte.
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas")

    auditoria.registrar(
        db,
        organizacion_id=organizacion.id,
        accion="login",
        entidad="sesion",
        # Una sesión no es una fila de ninguna tabla: `entidad_id` va vacío,
        # como en el evento de rate-limit. El actor va en `usuario_id`.
        entidad_id=None,
        usuario_id=usuario.id,
        detalle={"ip": ip},
    )
    db.commit()

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
