"""Errores de `/v1` (C.1, Bloque C): un único sobre JSON —`codigo`, `mensaje`,
`detalle`, `request_id`— para `ErrorDeDominio`, `RequestValidationError`,
`HTTPException` y la excepción no controlada (`app/main.py`). También cubre
`app/main.py::unhandled_exception_handler`, que discrimina por superficie
(A.3.5): un 500 en `/v1` sigue siendo JSON; uno en `app/web` es una página
HTML mínima, sin la excepción real."""
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
    cuerpo = respuesta.json()
    assert cuerpo["codigo"] == "error_interno"
    assert cuerpo["mensaje"] == "Error interno"
    assert cuerpo["detalle"] is None
    assert cuerpo["request_id"]
    assert cuerpo["detail"] == "Error interno"  # alias de compatibilidad durante F1


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


# --- C.1: sobre único de error en /v1 --------------------------------------


def test_http_exception_con_detail_de_texto_en_v1_usa_el_codigo_por_status(client):
    """404 con `detail` de texto (`_obtener_o_404`, expedientes.py): sin
    "codigo" propio, se le asigna el genérico de su status_code."""
    registro, contrasena = _registrar(client)
    token = client.post(
        "/v1/auth/login",
        json={
            "organizacion": registro["organizacion_slug"],
            "email": registro["email"],
            "contrasena": contrasena,
        },
    ).json()["access_token"]

    respuesta = client.get(
        "/v1/expedientes/00000000-0000-0000-0000-000000000000",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert respuesta.status_code == 404
    cuerpo = respuesta.json()
    assert cuerpo["codigo"] == "no_encontrado"
    assert cuerpo["mensaje"] == "Expediente no encontrado"
    assert cuerpo["detalle"] is None
    assert cuerpo["request_id"]
    assert cuerpo["detail"] == "Expediente no encontrado"  # alias de compatibilidad durante F1


def test_http_exception_con_detail_dict_conserva_su_propio_codigo(client):
    """`responsable_invalido` (A5.3) ya viaja como `{"codigo", "mensaje"}`:
    el handler de C.1 lo respeta tal cual en vez de sustituirlo por el
    genérico de 422."""
    registro, contrasena = _registrar(client)
    token = client.post(
        "/v1/auth/login",
        json={
            "organizacion": registro["organizacion_slug"],
            "email": registro["email"],
            "contrasena": contrasena,
        },
    ).json()["access_token"]

    respuesta = client.post(
        "/v1/expedientes",
        json={
            "identificador": "EXP-2026-777",
            "tipo_identificador": "sin_radicar",
            "seguimiento": "manual",
            "tipo_proceso": "civil",
            "responsable_usuario_id": "00000000-0000-0000-0000-000000000000",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert respuesta.status_code == 422
    cuerpo = respuesta.json()
    assert cuerpo["codigo"] == "responsable_invalido"
    assert cuerpo["request_id"]
    assert cuerpo["detail"]["codigo"] == "responsable_invalido"  # alias de compatibilidad


def test_error_de_validacion_en_v1_lleva_detalle_por_campo(client):
    """`RequestValidationError` (Pydantic) también usa el sobre de C.1, con
    `detalle` como lista de `{"campo", "problema"}`."""
    respuesta = client.post(
        "/v1/auth/registro",
        json={
            "nombre_organizacion": "Bufete Infante",
            "nombre": "Juan Diego Infante",
            "email": "juan.diego@example.com",
            "contrasena": "corta",  # min_length=8 en RegistroRequest
        },
    )

    assert respuesta.status_code == 422
    cuerpo = respuesta.json()
    assert cuerpo["codigo"] == "validacion"
    assert cuerpo["request_id"]
    assert cuerpo["detalle"]
    assert any(item["campo"] == "contrasena" for item in cuerpo["detalle"])
    assert isinstance(cuerpo["detail"], list)  # alias de compatibilidad, formato Pydantic


def test_error_de_validacion_fuera_de_v1_conserva_el_formato_por_defecto(client):
    """Un `offset` inválido en `app/web` (`GET /expedientes?offset=-1`) sigue
    respondiendo con el `{"detail": [...]}` de FastAPI: la validación ahí
    nunca formó parte del contrato público de C.1."""
    registro, contrasena = _registrar(client)
    client.post(
        "/login",
        data={
            "organizacion": registro["organizacion_slug"],
            "email": registro["email"],
            "contrasena": contrasena,
        },
        follow_redirects=False,
    )

    respuesta = client.get("/expedientes?offset=-1")

    assert respuesta.status_code == 422
    cuerpo = respuesta.json()
    assert "codigo" not in cuerpo
    assert isinstance(cuerpo["detail"], list)
