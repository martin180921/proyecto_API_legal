"""`/v1/expedientes`: camino feliz y error principal de cada endpoint,
validación del radicado, y prueba cruzada de tenancy (parada P3)."""
import pytest

from app.core.config import settings
from app.models.evento_auditoria import EventoAuditoria
from app.models.expediente import Expediente

RADICADO_VALIDO = "12345678901234567890123"
RADICADO_VALIDO_2 = "98765432109876543210987"


@pytest.fixture(autouse=True)
def _registro_abierto(monkeypatch):
    monkeypatch.setattr(settings, "registro_abierto", True)


def _registrar_y_loguear(
    client, nombre_organizacion="Bufete Infante", email="juan.diego@example.com"
):
    contrasena = "clave-larga-1"
    registro = client.post(
        "/v1/auth/registro",
        json={
            "nombre_organizacion": nombre_organizacion,
            "email": email,
            "contrasena": contrasena,
        },
    ).json()
    token = client.post(
        "/v1/auth/login",
        json={"organizacion": registro["organizacion_slug"], "email": email, "contrasena": contrasena},
    ).json()["access_token"]
    return registro, {"Authorization": f"Bearer {token}"}


def _payload(radicado=RADICADO_VALIDO, **overrides):
    payload = {
        "radicado": radicado,
        "juzgado": "Juzgado Primero Civil del Circuito",
        "despacho": "Despacho 001",
        "partes": "Demandante vs Demandado",
        "tipo_proceso": "civil",
        "ultima_actuacion_conocida": "Auto admisorio",
    }
    payload.update(overrides)
    return payload


# --- POST /v1/expedientes -----------------------------------------------


def test_crear_expediente_devuelve_201_con_auditoria(client, db_session):
    _, cabeceras = _registrar_y_loguear(client)

    respuesta = client.post("/v1/expedientes", json=_payload(), headers=cabeceras)

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["radicado"] == RADICADO_VALIDO
    assert cuerpo["tipo_proceso"] == "civil"
    assert cuerpo["activo"] is True

    expediente = db_session.get(Expediente, cuerpo["id"])
    assert expediente is not None

    evento = (
        db_session.query(EventoAuditoria)
        .filter_by(entidad="expediente", entidad_id=expediente.id, accion="crear")
        .one()
    )
    assert evento.organizacion_id == expediente.organizacion_id


def test_crear_expediente_sin_token_devuelve_401(client):
    respuesta = client.post("/v1/expedientes", json=_payload())
    assert respuesta.status_code == 401


@pytest.mark.parametrize(
    "radicado",
    [
        "123",  # demasiado corto
        "1234567890123456789012a",  # no numérico
        "123456789012345678901234",  # 24 dígitos, uno de más
    ],
)
def test_crear_expediente_con_radicado_invalido_devuelve_422(client, radicado):
    _, cabeceras = _registrar_y_loguear(client)

    respuesta = client.post("/v1/expedientes", json=_payload(radicado=radicado), headers=cabeceras)

    assert respuesta.status_code == 422


def test_crear_expediente_con_radicado_duplicado_en_la_misma_organizacion_devuelve_409(client):
    _, cabeceras = _registrar_y_loguear(client)
    assert client.post("/v1/expedientes", json=_payload(), headers=cabeceras).status_code == 201

    respuesta = client.post("/v1/expedientes", json=_payload(), headers=cabeceras)

    assert respuesta.status_code == 409


def test_mismo_radicado_en_organizaciones_distintas_no_choca(client):
    """El radicado es único por organización, no global."""
    _, cabeceras_a = _registrar_y_loguear(client, nombre_organizacion="Bufete A", email="a@example.com")
    _, cabeceras_b = _registrar_y_loguear(client, nombre_organizacion="Bufete B", email="b@example.com")

    assert client.post("/v1/expedientes", json=_payload(), headers=cabeceras_a).status_code == 201
    assert client.post("/v1/expedientes", json=_payload(), headers=cabeceras_b).status_code == 201


# --- GET /v1/expedientes (paginado) --------------------------------------


def test_listar_expedientes_devuelve_solo_los_de_la_organizacion_del_actor(client):
    _, cabeceras_a = _registrar_y_loguear(client, nombre_organizacion="Bufete A", email="a@example.com")
    _, cabeceras_b = _registrar_y_loguear(client, nombre_organizacion="Bufete B", email="b@example.com")

    client.post("/v1/expedientes", json=_payload(), headers=cabeceras_a)
    client.post("/v1/expedientes", json=_payload(radicado=RADICADO_VALIDO_2), headers=cabeceras_a)
    client.post("/v1/expedientes", json=_payload(), headers=cabeceras_b)

    respuesta = client.get("/v1/expedientes", headers=cabeceras_a)

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["total"] == 2
    assert len(cuerpo["items"]) == 2


def test_listar_expedientes_respeta_limit_y_offset(client):
    _, cabeceras = _registrar_y_loguear(client)
    for indice in range(3):
        client.post(
            "/v1/expedientes",
            json=_payload(radicado=f"1000000000000000000000{indice}"),
            headers=cabeceras,
        )

    respuesta = client.get("/v1/expedientes?limit=2&offset=1", headers=cabeceras)

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["total"] == 3
    assert len(cuerpo["items"]) == 2


def test_listar_expedientes_sin_token_devuelve_401(client):
    respuesta = client.get("/v1/expedientes")
    assert respuesta.status_code == 401


# --- GET /v1/expedientes/{id} --------------------------------------------


def test_obtener_expediente_devuelve_200(client):
    _, cabeceras = _registrar_y_loguear(client)
    creado = client.post("/v1/expedientes", json=_payload(), headers=cabeceras).json()

    respuesta = client.get(f"/v1/expedientes/{creado['id']}", headers=cabeceras)

    assert respuesta.status_code == 200
    assert respuesta.json()["id"] == creado["id"]


def test_obtener_expediente_inexistente_devuelve_404(client):
    _, cabeceras = _registrar_y_loguear(client)

    respuesta = client.get("/v1/expedientes/00000000-0000-0000-0000-000000000000", headers=cabeceras)

    assert respuesta.status_code == 404


# --- PATCH /v1/expedientes/{id} -------------------------------------------


def test_actualizar_expediente_devuelve_200_con_auditoria(client, db_session):
    _, cabeceras = _registrar_y_loguear(client)
    creado = client.post("/v1/expedientes", json=_payload(), headers=cabeceras).json()

    respuesta = client.patch(
        f"/v1/expedientes/{creado['id']}",
        json={"despacho": "Despacho 002", "ultima_actuacion_conocida": "Traslado"},
        headers=cabeceras,
    )

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["despacho"] == "Despacho 002"
    assert cuerpo["ultima_actuacion_conocida"] == "Traslado"
    # Lo no enviado no cambia.
    assert cuerpo["radicado"] == RADICADO_VALIDO

    evento = (
        db_session.query(EventoAuditoria)
        .filter_by(entidad="expediente", entidad_id=creado["id"], accion="actualizar")
        .one()
    )
    assert set(evento.detalle["campos"]) == {"despacho", "ultima_actuacion_conocida"}


def test_actualizar_expediente_inexistente_devuelve_404(client):
    _, cabeceras = _registrar_y_loguear(client)

    respuesta = client.patch(
        "/v1/expedientes/00000000-0000-0000-0000-000000000000",
        json={"despacho": "Despacho 002"},
        headers=cabeceras,
    )

    assert respuesta.status_code == 404


def test_actualizar_expediente_con_radicado_invalido_devuelve_422(client):
    _, cabeceras = _registrar_y_loguear(client)
    creado = client.post("/v1/expedientes", json=_payload(), headers=cabeceras).json()

    respuesta = client.patch(
        f"/v1/expedientes/{creado['id']}", json={"radicado": "123"}, headers=cabeceras
    )

    assert respuesta.status_code == 422


# --- POST /v1/expedientes/{id}/archivar -----------------------------------


def test_archivar_expediente_pone_activo_false_con_auditoria(client, db_session):
    _, cabeceras = _registrar_y_loguear(client)
    creado = client.post("/v1/expedientes", json=_payload(), headers=cabeceras).json()

    respuesta = client.post(f"/v1/expedientes/{creado['id']}/archivar", headers=cabeceras)

    assert respuesta.status_code == 200
    assert respuesta.json()["activo"] is False

    evento = (
        db_session.query(EventoAuditoria)
        .filter_by(entidad="expediente", entidad_id=creado["id"], accion="archivar")
        .one()
    )
    assert evento is not None


def test_archivar_expediente_inexistente_devuelve_404(client):
    _, cabeceras = _registrar_y_loguear(client)

    respuesta = client.post(
        "/v1/expedientes/00000000-0000-0000-0000-000000000000/archivar", headers=cabeceras
    )

    assert respuesta.status_code == 404


# --- Tenancy cruzada -------------------------------------------------------


def test_expediente_de_otra_organizacion_no_es_visible_ni_editable(client):
    """Mismo patrón que `test_token_con_organizacion_distinta_a_la_del_usuario_devuelve_401`
    de `tests/test_auth.py`, adaptado a un endpoint que sí lee datos de
    negocio: un expediente de la organización A no es visible ni editable con
    el token de la organización B."""
    _, cabeceras_a = _registrar_y_loguear(client, nombre_organizacion="Bufete A", email="a@example.com")
    _, cabeceras_b = _registrar_y_loguear(client, nombre_organizacion="Bufete B", email="b@example.com")

    creado = client.post("/v1/expedientes", json=_payload(), headers=cabeceras_a).json()
    expediente_id = creado["id"]

    assert client.get(f"/v1/expedientes/{expediente_id}", headers=cabeceras_b).status_code == 404
    assert (
        client.patch(
            f"/v1/expedientes/{expediente_id}", json={"despacho": "otro"}, headers=cabeceras_b
        ).status_code
        == 404
    )
    assert (
        client.post(f"/v1/expedientes/{expediente_id}/archivar", headers=cabeceras_b).status_code
        == 404
    )

    listado_b = client.get("/v1/expedientes", headers=cabeceras_b).json()
    assert listado_b["total"] == 0

    # El expediente de A sigue intacto: ninguna de las llamadas desde B lo tocó.
    respuesta_a = client.get(f"/v1/expedientes/{expediente_id}", headers=cabeceras_a)
    assert respuesta_a.status_code == 200
    assert respuesta_a.json()["activo"] is True
