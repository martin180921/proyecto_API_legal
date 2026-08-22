"""`app/main.py::unhandled_exception_handler`: discrimina por superficie
(A.3.5). Una excepción no controlada en `/v1` sigue devolviendo el JSON de
siempre; una en `app/web` devuelve una página HTML mínima, sin la excepción
real."""
import pytest

from app.core.config import settings
from app.services import expedientes


@pytest.fixture(autouse=True)
def _registro_abierto(monkeypatch):
    monkeypatch.setattr(settings, "registro_abierto", True)


@pytest.fixture()
def client(db_session):
    """Sombra al `client` de `conftest.py` solo en este módulo, con
    `raise_server_exceptions=False`: estas pruebas fuerzan a propósito una
    excepción no controlada para comprobar `unhandled_exception_handler`, y
    con el valor por defecto (`True`) el `TestClient` la vuelve a lanzar en
    el proceso de pytest en vez de dejar que el handler registrado en
    `app/main.py` construya la respuesta — que es justo lo que hay que
    observar aquí."""
    from fastapi.testclient import TestClient

    from app.core.db import get_db
    from app.main import app

    def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    try:
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)


def _registrar(client, nombre_organizacion="Bufete Infante", email="juan.diego@example.com"):
    contrasena = "clave-larga-1"
    registro = client.post(
        "/v1/auth/registro",
        json={
            "nombre_organizacion": nombre_organizacion,
            "nombre": "Juan Diego Infante",
            "email": email,
            "contrasena": contrasena,
        },
    ).json()
    return registro, contrasena


def _explota(*args, **kwargs):
    # El mensaje lleva algo que NO debe llegar nunca a la respuesta HTML: es
    # lo que las pruebas comprueban que se queda solo en el log.
    raise RuntimeError("fallo forzado por la prueba, con datos sensibles: secreto-123")


def test_excepcion_no_controlada_en_la_api_sigue_devolviendo_json(client, monkeypatch):
    registro, contrasena = _registrar(client)
    token = client.post(
        "/v1/auth/login",
        json={
            "organizacion": registro["organizacion_slug"],
            "email": registro["email"],
            "contrasena": contrasena,
        },
    ).json()["access_token"]
    monkeypatch.setattr(expedientes, "listar", _explota)

    respuesta = client.get("/v1/expedientes", headers={"Authorization": f"Bearer {token}"})

    assert respuesta.status_code == 500
    assert respuesta.headers["content-type"].startswith("application/json")
    assert respuesta.json() == {"detail": "Error interno"}


def test_excepcion_no_controlada_en_la_web_devuelve_html_sin_la_excepcion_real(client, monkeypatch):
    registro, contrasena = _registrar(client)
    login = client.post(
        "/login",
        data={
            "organizacion": registro["organizacion_slug"],
            "email": registro["email"],
            "contrasena": contrasena,
        },
        follow_redirects=False,
    )
    assert login.status_code == 303
    monkeypatch.setattr(expedientes, "listar", _explota)

    respuesta = client.get("/expedientes")

    assert respuesta.status_code == 500
    assert respuesta.headers["content-type"].startswith("text/html")
    assert "Traceback" not in respuesta.text
    assert "secreto-123" not in respuesta.text
    assert "RuntimeError" not in respuesta.text


def test_peticion_que_revienta_deja_linea_de_log_con_request_id(client, monkeypatch, caplog):
    """Revisión P4 (2026-08-22): el handler global de Exception corre por
    fuera del middleware `log_requests`, así que cuando `call_next` lanzaba,
    esa petición —justo la que más falta hace correlacionar— se quedaba sin
    línea de log. Con el try/finally, la línea sale siempre, con su
    `request_id` y `status_code=500`."""
    registro, contrasena = _registrar(client)
    token = client.post(
        "/v1/auth/login",
        json={
            "organizacion": registro["organizacion_slug"],
            "email": registro["email"],
            "contrasena": contrasena,
        },
    ).json()["access_token"]
    monkeypatch.setattr(expedientes, "listar", _explota)

    with caplog.at_level("INFO", logger="api_legal"):
        respuesta = client.get("/v1/expedientes", headers={"Authorization": f"Bearer {token}"})

    assert respuesta.status_code == 500
    lineas = [
        r for r in caplog.records if r.message == "request" and r.path == "/v1/expedientes"
    ]
    assert len(lineas) == 1
    assert lineas[0].status_code == 500
    assert lineas[0].request_id  # UUID no vacío: la correlación sobrevive al fallo
