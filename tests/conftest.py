"""Fixtures compartidas. **Las pruebas corren contra Postgres, no SQLite.**

Por qué (decidido el 2026-08-05, ver [[Las pruebas corren contra Postgres]] en
la bóveda): SQLite ya dio un falso verde en la revisión de P1 — no validaba
las claves foráneas, así que un `organizacion_id` huérfano pasaba en verde y
habría reventado en producción. Además el `REVOKE` de T3 es DDL de Postgres:
sobre SQLite las migraciones ni siquiera se pueden ejecutar, así que no se
probaban en ningún sitio.

Cómo funciona:

- El esquema lo crea `alembic upgrade head`, **no** `Base.metadata.create_all`.
  Así cada ejecución de la suite prueba también las migraciones: si el modelo
  y la migración se separan, los tests se enteran.
- Se ejecuta una vez por sesión de pytest (fixture con `scope="session"`).
- Cada test corre dentro de una transacción que se revierte al terminar, así
  que la base de datos vuelve a su estado anterior sin recrear el esquema.

El rol de las pruebas es **no superusuario** a propósito: un superusuario se
salta los `GRANT`/`REVOKE` sin avisar y volvería vacía la prueba de
inmutabilidad del audit log. Ver `tests/test_auditoria.py`.
"""
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# La URL de pruebas se fija ANTES de importar nada de `app`, porque
# `app.core.config` lee el entorno al importarse. Coincide con el servicio de
# `docker-compose.yml` y con el de `.github/workflows/ci.yml`.
URL_PRUEBAS_POR_DEFECTO = (
    "postgresql+psycopg://api_legal_app:api_legal_app@localhost:5432/api_legal_test"
)
URL_PRUEBAS = os.environ.get("DATABASE_URL_TEST", URL_PRUEBAS_POR_DEFECTO)

# Red de seguridad: la suite borra y reescribe datos. Que no pueda apuntar a
# producción ni por accidente ni por una variable de entorno mal puesta.
for señal in ("railway.app", "rlwy.net", "proyectoapilegal"):
    if señal in URL_PRUEBAS:
        raise RuntimeError(
            f"DATABASE_URL_TEST apunta a algo que parece producción ({señal}). "
            "Las pruebas escriben y borran: apúntala a la base de datos local."
        )

os.environ["DATABASE_URL"] = URL_PRUEBAS

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

import app.models  # noqa: E402,F401 — registra los modelos en Base.metadata

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="session")
def engine():
    motor = create_engine(URL_PRUEBAS)
    try:
        with motor.connect() as conexion:
            conexion.execute(text("select 1"))
    except Exception as error:  # pragma: no cover — camino de diagnóstico
        pytest.exit(
            "No hay Postgres de pruebas escuchando en "
            f"{URL_PRUEBAS.rsplit('@', 1)[-1]}.\n"
            "Levántala con `docker compose up -d db` (ver README).\n"
            f"Error original: {error}",
            returncode=1,
        )

    # El esquema sale de las migraciones, no de create_all: así la suite
    # también prueba que las migraciones corren y dicen lo mismo que el modelo.
    configuracion = Config(os.path.join(RAIZ, "alembic.ini"))
    configuracion.set_main_option("script_location", os.path.join(RAIZ, "alembic"))
    command.upgrade(configuracion, "head")

    yield motor
    motor.dispose()


@pytest.fixture()
def db_session(engine):
    """Sesión envuelta en una transacción que se revierte al final de cada
    test, para que no se contaminen entre sí."""
    conexion = engine.connect()
    transaccion = conexion.begin()
    SesionDePrueba = sessionmaker(bind=conexion, autoflush=False, autocommit=False)
    sesion = SesionDePrueba()

    try:
        yield sesion
    finally:
        sesion.close()
        # Un IntegrityError durante el test ya deja la transacción revertida
        # por dentro; solo cerramos la nuestra si SQLAlchemy no lo hizo ya.
        if transaccion.is_active:
            transaccion.rollback()
        conexion.close()


@pytest.fixture(autouse=True)
def _reiniciar_rate_limit():
    """El contador de `app/core/rate_limit.py` vive en memoria del proceso,
    no en la base de datos: sin esto, los intentos fallidos de un test de
    login se acumularían sobre el siguiente dentro de la misma sesión de
    pytest."""
    from app.core import rate_limit

    rate_limit.reiniciar()
    yield
    rate_limit.reiniciar()


@pytest.fixture()
def client(db_session):
    """`TestClient` con `get_db` sustituido por la sesión transaccional de
    `db_session`. Los endpoints llaman a `db.commit()`, pero como la sesión
    está unida a una conexión que ya tiene una transacción abierta desde
    fuera, ese commit solo hace `flush` — es el patrón documentado de
    SQLAlchemy para pruebas ("Joining a Session into an External
    Transaction"). El `transaccion.rollback()` de `db_session` sigue
    limpiando todo al final del test."""
    from fastapi.testclient import TestClient

    from app.core.db import get_db
    from app.main import app

    def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)
