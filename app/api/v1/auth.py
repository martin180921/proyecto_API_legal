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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.rate_limit import limite_superado, registrar_intento
from app.core.security import EXPIRACION_TOKEN, ActorActual, hash_contrasena, usuario_actual
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
from app.services.autenticacion import intentar_login

router = APIRouter(prefix="/auth", tags=["auth"])

# Tope de reintentos ante una colisión de slug. Con tres ya se ha probado un
# sufijo aleatorio nuevo dos veces; si aún choca, no es concurrencia, es otra
# cosa — y un bucle sin tope en un endpoint público es un problema peor que el
# que resuelve.
MAXIMO_INTENTOS_SLUG = 3


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


def _crear_organizacion_y_usuario(
    db: Session, payload: RegistroRequest
) -> tuple[Organizacion, Usuario]:
    """Crea la organización, su primer usuario y los dos eventos de auditoría.

    Está fuera del endpoint para que el reintento por colisión de slug pueda
    repetirla entera: tras un `rollback` no queda nada en pie, ni la
    organización ni el usuario ni los eventos, así que reintentar solo el
    `INSERT` de la organización dejaría el resto huérfano.
    """
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
    return organizacion, usuario


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

    # `_generar_slug_unico` consulta y luego inserta, así que dos registros
    # concurrentes con el mismo nombre pueden elegir el mismo slug y chocar
    # contra el índice único. Sin capturarlo, el IntegrityError sube sin más:
    # 500 genérico y sesión en estado inconsistente. Con un solo usuario no
    # pasa nunca; es de los defectos que solo aparecen el día que importa.
    #
    # Se reintenta con un sufijo nuevo —la siguiente llamada ya ve el slug
    # ocupado— y con un tope, nunca un bucle infinito. Agotados los intentos
    # es un conflicto de verdad, y eso es un 409, no un 500.
    for _ in range(MAXIMO_INTENTOS_SLUG):
        try:
            organizacion, usuario = _crear_organizacion_y_usuario(db, payload)
            break
        except IntegrityError:
            db.rollback()
    else:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se pudo crear la organización. Vuelve a intentarlo.",
        )

    return RegistroResponse(
        organizacion_id=organizacion.id,
        organizacion_slug=organizacion.slug,
        usuario_id=usuario.id,
        email=usuario.email,
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    # Núcleo compartido con `app/web` (cookie httpOnly, mismo JWT) — ver
    # `app/services/autenticacion.py`. Mismo comportamiento que antes de la
    # extracción: 401/429 en los mismos casos, mismos eventos de auditoría.
    resultado = intentar_login(db, payload.organizacion, payload.email, payload.contrasena, _ip_cliente(request))
    return TokenResponse(
        access_token=resultado.token,
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
