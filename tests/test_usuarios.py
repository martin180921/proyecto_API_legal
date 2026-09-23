"""`/v1/usuarios` — lectura para el selector de responsable del SPA (C.5,
Bloque C)."""
import pytest

from app.core.config import settings


@pytest.fixture(autouse=True)
def _registro_abierto(monkeypatch):
    monkeypatch.setattr(settings, "registro_abierto", True)


def _registrar_y_loguear(client, nombre_organizacion="Bufete Infante", email="juan.diego@example.com"):
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
    token = client.post(
        "/v1/auth/login",
        json={"organizacion": registro["organizacion_slug"], "email": email, "contrasena": contrasena},
    ).json()["access_token"]
    return registro, {"Authorization": f"Bearer {token}"}


def test_listar_usuarios_devuelve_los_de_la_organizacion_del_actor(client):
    registro, cabeceras = _registrar_y_loguear(client)

    respuesta = client.get("/v1/usuarios", headers=cabeceras)

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert len(cuerpo["items"]) == 1
    assert cuerpo["items"][0]["id"] == registro["usuario_id"]
    assert cuerpo["items"][0]["email"] == registro["email"]
    assert cuerpo["items"][0]["activo"] is True


def test_listar_usuarios_no_ve_los_de_otra_organizacion(client):
    _, cabeceras_a = _registrar_y_loguear(client, nombre_organizacion="Bufete A", email="a@example.com")
    _registrar_y_loguear(client, nombre_organizacion="Bufete B", email="b@example.com")

    cuerpo = client.get("/v1/usuarios", headers=cabeceras_a).json()

    assert len(cuerpo["items"]) == 1
    assert cuerpo["items"][0]["email"] == "a@example.com"


def test_listar_usuarios_sin_token_devuelve_401(client):
    respuesta = client.get("/v1/usuarios")
    assert respuesta.status_code == 401


def test_listar_usuarios_con_usuario_desactivado_devuelve_401(client, db_session):
    """Mismo criterio que las rutas de lectura de expedientes desde A5.1:
    `usuario_actual_verificado` corta el acceso de inmediato, no hasta que
    expire el JWT."""
    from app.models.usuario import Usuario

    registro, cabeceras = _registrar_y_loguear(client)
    usuario = db_session.get(Usuario, registro["usuario_id"])
    usuario.activo = False
    db_session.flush()

    respuesta = client.get("/v1/usuarios", headers=cabeceras)

    assert respuesta.status_code == 401
