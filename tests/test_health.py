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
