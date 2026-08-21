"""`app/web`: login por cookie, lista y alta de expedientes. Camino feliz y
error principal de cada ruta, más la redirección cuando no hay sesión y la
tenancy cruzada (mismo criterio que `tests/test_expedientes.py`)."""
import pytest

from app.core.config import settings
from app.models.evento_auditoria import EventoAuditoria
from app.models.expediente import Expediente

IDENTIFICADOR_VALIDO = "12345678901234567890123"


@pytest.fixture(autouse=True)
def _registro_abierto(monkeypatch):
    monkeypatch.setattr(settings, "registro_abierto", True)


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


def _login_web(client, slug, email, contrasena, cabeceras=None):
    return client.post(
        "/login",
        data={"organizacion": slug, "email": email, "contrasena": contrasena},
        follow_redirects=False,
        headers=cabeceras or {},
    )


def _registrar_y_loguear_web(client, **kwargs):
    registro, contrasena = _registrar(client, **kwargs)
    respuesta = _login_web(client, registro["organizacion_slug"], registro["email"], contrasena)
    assert respuesta.status_code == 303
    return registro, contrasena


def _crear_expediente_via_api(client, registro, contrasena, identificador=IDENTIFICADOR_VALIDO):
    """Da de alta un expediente por la API JSON (con su propio bearer token,
    sin tocar la cookie de sesión web que el `client` ya tenga puesta)."""
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
            "identificador": identificador,
            "tipo_identificador": "radicado_unificado",
            "seguimiento": "automatico",
            "tipo_proceso": "civil",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert respuesta.status_code == 201


# --- Redirección sin sesión ------------------------------------------------


def test_expedientes_sin_cookie_redirige_a_login(client):
    respuesta = client.get("/expedientes", follow_redirects=False)
    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == "/login"


def test_raiz_redirige_a_expedientes(client):
    respuesta = client.get("/", follow_redirects=False)
    assert respuesta.status_code == 307
    assert respuesta.headers["location"] == "/expedientes"


# --- Login web --------------------------------------------------------------


def test_login_web_con_contrasena_incorrecta_muestra_error_sin_poner_cookie(client):
    registro, _ = _registrar(client)

    respuesta = _login_web(client, registro["organizacion_slug"], "juan.diego@example.com", "mala")

    assert respuesta.status_code == 401
    assert "Credenciales inválidas" in respuesta.text
    assert "sesion" not in respuesta.cookies


def test_login_web_correcto_pone_cookie_y_redirige_a_expedientes(client):
    registro, contrasena = _registrar(client)

    respuesta = _login_web(client, registro["organizacion_slug"], "juan.diego@example.com", contrasena)

    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == "/expedientes"
    assert "sesion" in respuesta.cookies


def test_en_produccion_login_web_usa_ip_de_x_forwarded_for(client, db_session, monkeypatch):
    """`app/web` reintrodujo el 2026-08-15 el bug de la IP del proxy que el
    arreglo #6 (2026-08-08) ya había cerrado en la API: `request.client.host`
    en Railway es la IP del *edge*, la misma para todo el tráfico, así que el
    rate-limit y el audit log de la web quedaban colapsados en una sola clave
    por organización. Mismo patrón que
    `test_auth.py::test_en_produccion_se_usa_la_ip_de_x_forwarded_for`."""
    monkeypatch.setattr(settings, "app_env", "production")
    registro, _ = _registrar(client)

    _login_web(
        client,
        registro["organizacion_slug"],
        "juan.diego@example.com",
        "mala",
        cabeceras={"X-Forwarded-For": "203.0.113.7"},
    )

    evento = (
        db_session.query(EventoAuditoria)
        .filter_by(organizacion_id=registro["organizacion_id"], accion="login_fallido")
        .one()
    )
    assert evento.detalle["ip"] == "203.0.113.7"


def test_logout_borra_la_cookie_y_expedientes_vuelve_a_exigir_login(client):
    _registrar_y_loguear_web(client)

    respuesta = client.post("/logout", follow_redirects=False)
    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == "/login"

    tras_logout = client.get("/expedientes", follow_redirects=False)
    assert tras_logout.status_code == 303
    assert tras_logout.headers["location"] == "/login"


def test_get_logout_devuelve_405(client):
    """Cerrar sesión con un GET es CSRF-able con un `<img src="…/logout">` en
    cualquier página o correo — un GET no debe mutar estado."""
    _registrar_y_loguear_web(client)

    respuesta = client.get("/logout", follow_redirects=False)
    assert respuesta.status_code == 405


# --- Lista de expedientes ----------------------------------------------------


def test_lista_de_expedientes_muestra_solo_los_de_la_organizacion(client):
    registro_a, contrasena_a = _registrar_y_loguear_web(client, nombre_organizacion="Bufete A", email="a@example.com")
    _crear_expediente_via_api(client, registro_a, contrasena_a)

    respuesta = client.get("/expedientes")
    assert respuesta.status_code == 200
    assert IDENTIFICADOR_VALIDO in respuesta.text
    assert "Expedientes (1)" in respuesta.text


def test_lista_de_expedientes_no_muestra_los_de_otra_organizacion(client):
    registro_a, contrasena_a = _registrar_y_loguear_web(client, nombre_organizacion="Bufete A", email="a@example.com")
    _crear_expediente_via_api(client, registro_a, contrasena_a)

    # Otra organización, otra sesión: el client comparte cookies, así que el
    # segundo login sobreescribe la cookie del primero.
    _registrar_y_loguear_web(client, nombre_organizacion="Bufete B", email="b@example.com")

    respuesta = client.get("/expedientes")
    assert respuesta.status_code == 200
    assert IDENTIFICADOR_VALIDO not in respuesta.text
    assert "Expedientes (0)" in respuesta.text


def test_lista_de_expedientes_marca_el_seguimiento_manual(client):
    """B.1: los expedientes de seguimiento manual se ven en la misma lista,
    con una marca clara — no desaparecen ni se confunden con los automáticos."""
    registro_a, contrasena_a = _registrar_y_loguear_web(client)
    token = client.post(
        "/v1/auth/login",
        json={
            "organizacion": registro_a["organizacion_slug"],
            "email": registro_a["email"],
            "contrasena": contrasena_a,
        },
    ).json()["access_token"]
    client.post(
        "/v1/expedientes",
        json={
            "identificador": "responsabilidad-fiscal-001",
            "tipo_identificador": "expediente_contraloria",
            "seguimiento": "manual",
            "tipo_proceso": "administrativo",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    respuesta = client.get("/expedientes")
    assert respuesta.status_code == 200
    assert "Revisas tú" in respuesta.text


def test_lista_de_expedientes_con_offset_negativo_devuelve_422(client):
    """La API ya valida `offset` (`Query(default=0, ge=0)`); la web no lo
    hacía, así que `offset=-1` llegaba a `.offset(-1)`, Postgres lo rechazaba
    y el abogado veía el JSON genérico de `app/main.py` en medio de una
    pantalla HTML."""
    _registrar_y_loguear_web(client)

    respuesta = client.get("/expedientes?offset=-1")
    assert respuesta.status_code == 422


# --- Alta de expediente -------------------------------------------------------


def test_alta_de_expediente_valida_redirige_y_deja_auditoria(client, db_session):
    registro, _ = _registrar_y_loguear_web(client)

    respuesta = client.post(
        "/expedientes/nuevo",
        data={
            "identificador": IDENTIFICADOR_VALIDO,
            "tipo_identificador": "radicado_unificado",
            "seguimiento": "automatico",
            "tipo_proceso": "civil",
            "juzgado": "Juzgado Primero Civil del Circuito",
            "partes": "Demandante vs Demandado",
        },
        follow_redirects=False,
    )

    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == "/expedientes"

    expediente = (
        db_session.query(Expediente)
        .filter_by(organizacion_id=registro["organizacion_id"], identificador=IDENTIFICADOR_VALIDO)
        .one()
    )
    assert expediente.juzgado == "Juzgado Primero Civil del Circuito"

    evento = (
        db_session.query(EventoAuditoria)
        .filter_by(entidad="expediente", entidad_id=expediente.id, accion="crear")
        .one()
    )
    assert str(evento.organizacion_id) == registro["organizacion_id"]


def test_alta_de_expediente_con_identificador_invalido_reforma_el_formulario_con_error(client, db_session):
    registro, _ = _registrar_y_loguear_web(client)

    respuesta = client.post(
        "/expedientes/nuevo",
        data={
            "identificador": "123",
            "tipo_identificador": "radicado_unificado",
            "seguimiento": "automatico",
            "tipo_proceso": "civil",
        },
    )

    assert respuesta.status_code == 400
    assert "23 dígitos" in respuesta.text or "23" in respuesta.text
    assert db_session.query(Expediente).filter_by(organizacion_id=registro["organizacion_id"]).count() == 0


def test_alta_de_expediente_sin_radicar_no_exige_23_digitos(client, db_session):
    """B.1: `sin_radicar` no lleva la CHECK de 23 dígitos — es justo el caso
    de la fila 81 del Excel de Juan Diego, una demanda que todavía no se ha
    radicado."""
    registro, _ = _registrar_y_loguear_web(client)

    respuesta = client.post(
        "/expedientes/nuevo",
        data={
            "identificador": "pendiente-de-radicar-fila-81",
            "tipo_identificador": "sin_radicar",
            "seguimiento": "manual",
            "tipo_proceso": "administrativo",
        },
        follow_redirects=False,
    )

    assert respuesta.status_code == 303
    assert (
        db_session.query(Expediente)
        .filter_by(organizacion_id=registro["organizacion_id"], identificador="pendiente-de-radicar-fila-81")
        .count()
        == 1
    )


def test_alta_de_expediente_con_identificador_duplicado_devuelve_409(client):
    _registrar_y_loguear_web(client)

    datos = {
        "identificador": IDENTIFICADOR_VALIDO,
        "tipo_identificador": "radicado_unificado",
        "seguimiento": "automatico",
        "tipo_proceso": "civil",
    }

    primero = client.post("/expedientes/nuevo", data=datos, follow_redirects=False)
    assert primero.status_code == 303

    segundo = client.post("/expedientes/nuevo", data=datos)
    assert segundo.status_code == 409
    assert "Ya existe" in segundo.text


def test_alta_de_expediente_sin_cookie_redirige_a_login(client):
    respuesta = client.post(
        "/expedientes/nuevo",
        data={
            "identificador": IDENTIFICADOR_VALIDO,
            "tipo_identificador": "radicado_unificado",
            "seguimiento": "automatico",
            "tipo_proceso": "civil",
        },
        follow_redirects=False,
    )
    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == "/login"
