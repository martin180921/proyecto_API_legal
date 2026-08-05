"""La `DATABASE_URL` que inyecta Railway usa el esquema `postgresql://`, que
SQLAlchemy interpreta como psycopg2 — un driver que este proyecto no instala.
Sin normalizar, la app arranca, responde `/v1/health` y revienta con
`ModuleNotFoundError: psycopg2` en la primera petición que toque la base de
datos. Verificado el 2026-08-05."""
import pytest

from app.core.config import Settings


@pytest.mark.parametrize(
    "entrada",
    [
        "postgresql://u:p@host:5432/db",  # lo que da Railway
        "postgres://u:p@host:5432/db",  # variante de otros proveedores
    ],
)
def test_la_url_de_base_de_datos_fuerza_el_driver_psycopg(entrada):
    assert Settings(database_url=entrada).database_url == "postgresql+psycopg://u:p@host:5432/db"


def test_una_url_que_ya_trae_driver_no_se_toca():
    url = "postgresql+psycopg://u:p@host:5432/db"
    assert Settings(database_url=url).database_url == url
