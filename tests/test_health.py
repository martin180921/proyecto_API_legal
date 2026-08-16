"""Camino feliz + error principal, por Definition of Done del proyecto."""
import json

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.core.db import get_db
from app.main import app

client = TestClient(app)


def test_health_check_ok():
    """Camino feliz: /v1/health responde 200 con status ok."""
    response = client.get("/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "api-legal"


def test_unknown_route_returns_404():
    """Error principal: una ruta que no existe no debe caerse en 500."""
    response = client.get("/v1/ruta-que-no-existe")
    assert response.status_code == 404


def test_la_respuesta_trae_x_request_id():
    """A.3.3 (Bloque A2): cada respuesta lleva un `X-Request-ID` propio, para
    poder correlacionarla con la línea de log y con el evento de auditoría que
    haya podido producir."""
    response = client.get("/v1/health")
    assert response.headers["X-Request-ID"]


def test_dos_peticiones_traen_x_request_id_distintos():
    """Sin esto, dos peticiones concurrentes serían indistinguibles en el
    log: el `request_id` deja de servir para correlacionar nada."""
    primera = client.get("/v1/health")
    segunda = client.get("/v1/health")
    assert primera.headers["X-Request-ID"] != segunda.headers["X-Request-ID"]


def test_health_ready_ok():
    """Camino feliz: /v1/health/ready toca la base de verdad (Postgres de
    pruebas) y responde 200. A diferencia de /v1/health, este es el endpoint
    que debe vigilar Railway (A.1.4)."""
    response = client.get("/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}


def test_health_ready_devuelve_503_sin_filtrar_nada_de_la_conexion_si_la_base_falla():
    """Error principal: si Postgres falla, 503 con un mensaje genérico — ni la
    excepción de SQLAlchemy ni ningún fragmento de `DATABASE_URL` (usuario,
    host, contraseña) puede llegar al cuerpo, porque este endpoint es
    público. Se simula sustituyendo `get_db`, no tumbando la Postgres de
    pruebas — eso rompería el resto de la suite, que sí la necesita viva."""

    def _get_db_que_falla():
        class _SesionQueFalla:
            def execute(self, *args, **kwargs):
                raise OperationalError(
                    "SELECT 1",
                    {},
                    Exception(
                        "conexión rechazada a postgresql://api_legal_app:secreto-de-prueba@db-interna:5432/api_legal"
                    ),
                )

        yield _SesionQueFalla()

    app.dependency_overrides[get_db] = _get_db_que_falla
    try:
        response = client.get("/v1/health/ready")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    cuerpo = response.json()
    assert cuerpo == {"status": "error", "db": "error"}

    texto = json.dumps(cuerpo, ensure_ascii=False)
    assert "secreto-de-prueba" not in texto
    assert "postgresql://" not in texto
    assert "db-interna" not in texto
