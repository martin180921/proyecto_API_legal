"""`GET /v1/estado-fuentes` (P6): última corrida, conteo por resultado y los
`no_verificado` con su motivo, con tenancy."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.models.expediente import Expediente, Seguimiento, TipoIdentificador, TipoProceso
from app.models.proceso_fuente import FuenteProceso
from app.models.revision import ResultadoRevision, Revision
from app.models.usuario import Usuario

BASE = datetime(2026, 10, 6, 6, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _registro_abierto(monkeypatch):
    monkeypatch.setattr(settings, "registro_abierto", True)


def _registrar_y_loguear(client, nombre="Bufete A", email="a@example.com"):
    contrasena = "clave-larga-1"
    registro = client.post(
        "/v1/auth/registro",
        json={"nombre_organizacion": nombre, "nombre": "Abogado", "email": email, "contrasena": contrasena},
    ).json()
    token = client.post(
        "/v1/auth/login",
        json={"organizacion": registro["organizacion_slug"], "email": email, "contrasena": contrasena},
    ).json()["access_token"]
    return registro, {"Authorization": f"Bearer {token}"}


def _organizacion_id(db, registro):
    return db.get(Usuario, registro["usuario_id"]).organizacion_id


def _expediente(db, org_id, n):
    exp = Expediente(
        organizacion_id=org_id,
        identificador=f"{n:023d}",
        tipo_identificador=TipoIdentificador.RADICADO_UNIFICADO,
        seguimiento=Seguimiento.AUTOMATICO,
        tipo_proceso=TipoProceso.CIVIL,
    )
    db.add(exp)
    db.flush()
    return exp


def _revision(db, exp, resultado, corrida_id, minutos, detalle=None):
    rev = Revision(
        organizacion_id=exp.organizacion_id,
        expediente_id=exp.id,
        fuente=FuenteProceso.RAMA_JUDICIAL,
        resultado=resultado,
        corrida_id=corrida_id,
        detalle=detalle,
        revisado_en=BASE + timedelta(minutes=minutos),
    )
    db.add(rev)
    db.flush()
    return rev


def test_sin_corridas_devuelve_ultima_corrida_nula(client):
    _, cabeceras = _registrar_y_loguear(client)

    respuesta = client.get("/v1/estado-fuentes", headers=cabeceras)

    assert respuesta.status_code == 200
    assert respuesta.json()["ultima_corrida"] is None
    assert respuesta.json()["no_verificados"] == []


def test_devuelve_solo_la_ultima_corrida_con_conteo_y_motivos(client, db_session):
    registro, cabeceras = _registrar_y_loguear(client)
    org = _organizacion_id(db_session, registro)
    vieja, nueva = uuid.uuid4(), uuid.uuid4()
    e1, e2, e3 = (_expediente(db_session, org, n) for n in (1, 2, 3))
    # Corrida vieja: no debe contarse.
    _revision(db_session, e1, ResultadoRevision.NO_VERIFICADO, vieja, 0, "vieja")
    # Corrida nueva.
    _revision(db_session, e1, ResultadoRevision.SIN_NOVEDAD, nueva, 1440)
    _revision(db_session, e2, ResultadoRevision.NO_VERIFICADO, nueva, 1441, "circuito abierto")
    _revision(db_session, e3, ResultadoRevision.CON_NOVEDAD, nueva, 1442)
    # Revisión a mano, sin corrida_id, más reciente: no define «la última corrida».
    _revision(db_session, e3, ResultadoRevision.SIN_NOVEDAD, None, 2000)

    cuerpo = client.get("/v1/estado-fuentes", headers=cabeceras).json()

    assert cuerpo["ultima_corrida"]["corrida_id"] == str(nueva)
    assert cuerpo["ultima_corrida"]["total"] == 3
    assert cuerpo["ultima_corrida"]["resultados"] == {
        "con_novedad": 1,
        "sin_novedad": 1,
        "no_verificado": 1,
        "no_encontrado": 0,
    }
    assert cuerpo["no_verificados_total"] == 1
    assert len(cuerpo["no_verificados"]) == 1
    fila = cuerpo["no_verificados"][0]
    assert fila["expediente_id"] == str(e2.id)
    assert fila["identificador"] == e2.identificador
    assert fila["detalle"] == "circuito abierto"


def test_paginacion_de_no_verificados(client, db_session):
    registro, cabeceras = _registrar_y_loguear(client)
    org = _organizacion_id(db_session, registro)
    corrida = uuid.uuid4()
    for n in range(1, 4):
        _revision(db_session, _expediente(db_session, org, n), ResultadoRevision.NO_VERIFICADO, corrida, n, f"m{n}")

    cuerpo = client.get("/v1/estado-fuentes?limit=2&offset=2", headers=cabeceras).json()

    assert cuerpo["no_verificados_total"] == 3
    assert [f["detalle"] for f in cuerpo["no_verificados"]] == ["m3"]


def test_tenancy_no_ve_la_corrida_de_otra_organizacion(client, db_session):
    registro_a, cabeceras_a = _registrar_y_loguear(client, "Bufete A", "a@example.com")
    registro_b, _ = _registrar_y_loguear(client, "Bufete B", "b@example.com")
    exp_b = _expediente(db_session, _organizacion_id(db_session, registro_b), 9)
    _revision(db_session, exp_b, ResultadoRevision.NO_VERIFICADO, uuid.uuid4(), 0, "de B")

    cuerpo = client.get("/v1/estado-fuentes", headers=cabeceras_a).json()

    assert cuerpo["ultima_corrida"] is None
    assert cuerpo["no_verificados"] == []


def test_sin_token_devuelve_401_con_codigo_estable(client):
    respuesta = client.get("/v1/estado-fuentes")

    assert respuesta.status_code == 401
    assert respuesta.json()["codigo"] == "no_autenticado"


def test_limit_fuera_de_rango_devuelve_422_con_codigo_estable(client):
    _, cabeceras = _registrar_y_loguear(client)

    respuesta = client.get("/v1/estado-fuentes?limit=0", headers=cabeceras)

    assert respuesta.status_code == 422
    assert respuesta.json()["codigo"] == "validacion"
