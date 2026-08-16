"""Resolución de la IP real del cliente, compartida por `app/api/v1/auth.py`
y `app/web/router.py` (Bloque A1, 2026-08-16).

Extraída de `app/api/v1/auth.py`, donde nació el 2026-08-08 (arreglo #6):
`app/web` reintrodujo `request.client.host` sin pasar por aquí al construirse
el 2026-08-15, porque el refactor que creó `app/web/` extrajo el núcleo del
login (`app/services/autenticacion.py::intentar_login`) pero dejó la
resolución de la IP en cada llamador. La lección: cuando se extrae un núcleo
compartido, hay que extraer también sus entradas sensibles, o la duplicación
se reproduce en el borde.
"""
import ipaddress

from fastapi import Request

from app.core.config import settings


def ip_cliente(request: Request) -> str:
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
