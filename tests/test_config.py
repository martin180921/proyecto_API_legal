"""Pruebas de `app/core/config.py`.

Las dos cosas que se comprueban aquí son fallos **silenciosos** de despliegue:
la app arranca, `/v1/health` responde 200 y el healthcheck de Railway pasa, y
sin embargo está rota. Por eso se prueban en la configuración y no más arriba.

- La `DATABASE_URL` que inyecta Railway usa el esquema `postgresql://`, que
  SQLAlchemy interpreta como psycopg2 — un driver que este proyecto no instala.
  Sin normalizar revienta con `ModuleNotFoundError: psycopg2` en la primera
  petición que toque la base de datos. Verificado el 2026-08-05.
- La `SECRET_KEY` de ejemplo está en el repositorio público: desplegar con ella
  permite a cualquiera firmar un JWT válido para cualquier organización.
"""
import pytest
from pydantic import ValidationError

from app.core.config import LONGITUD_MINIMA_SECRET_KEY, Settings

CLAVE_REAL = "z" * LONGITUD_MINIMA_SECRET_KEY


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


@pytest.mark.parametrize(
    "clave",
    [
        "cambiar-en-produccion",  # el default de config.py y de .env.example
        "",  # variable puesta pero vacía
        "changeme",
        "corta-pero-no-de-ejemplo",  # 24 caracteres: no es de ejemplo, es corta
    ],
)
def test_produccion_rechaza_una_secret_key_de_ejemplo_o_corta(clave):
    with pytest.raises(ValidationError) as error:
        Settings(app_env="production", secret_key=clave)

    # El mensaje tiene que decir qué hacer, no solo que algo está mal: quien lo
    # lee está mirando los logs de un deploy que acaba de fallar.
    assert "secrets.token_urlsafe" in str(error.value)


def test_el_error_de_configuracion_no_filtra_secretos():
    """Este texto acaba en los logs de Railway, así que no puede llevar
    secretos dentro. Pydantic añade `input_value={...}` por defecto y ahí
    viaja la configuración entera — incluida la contraseña de la
    `DATABASE_URL`. Lo apaga `hide_input_in_errors` en `model_config`; si
    alguien lo quita, esta prueba lo detiene."""
    clave_rechazada = "corta-pero-secreta-1234"
    with pytest.raises(ValidationError) as error:
        Settings(
            app_env="production",
            secret_key=clave_rechazada,
            database_url="postgresql+psycopg://u:contrasena-de-postgres@host:5432/db",
        )

    texto = str(error.value)
    assert clave_rechazada not in texto
    assert "contrasena-de-postgres" not in texto


def test_produccion_con_una_secret_key_real_construye():
    settings = Settings(app_env="production", secret_key=CLAVE_REAL)
    assert settings.secret_key == CLAVE_REAL


def test_fuera_de_produccion_la_clave_de_ejemplo_no_estorba():
    """En local y en CI la clave de ejemplo es la correcta. La guarda solo
    existe para producción; si validara siempre, rompería el arranque de
    cualquiera que clone el repo y siga el README."""
    assert Settings(app_env="local", secret_key="cambiar-en-produccion").secret_key
