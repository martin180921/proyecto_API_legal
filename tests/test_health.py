"""Camino feliz + error principal, por Definition of Done del proyecto."""
from fastapi.testclient import TestClient

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
