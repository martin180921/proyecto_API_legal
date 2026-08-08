"""`/v1/auth`: registro, login (camino feliz y error principal), rate-limit
con evento de auditoría, y `/v1/auth/yo`."""
import json

from app.core import rate_limit
from app.models.evento_auditoria import EventoAuditoria
from app.models.organizacion import Organizacion
from app.models.usuario import Usuario


def _registrar(client, nombre_organizacion="Bufete Infante", email="juan.diego@example.com", contrasena="clave-larga-1"):
    return client.post(
        "/v1/auth/registro",
        json={
            "nombre_organizacion": nombre_organizacion,
            "email": email,
            "contrasena": contrasena,
        },
    )


def test_registro_crea_organizacion_y_usuario_con_auditoria(client, db_session):
    respuesta = _registrar(client)
    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["organizacion_slug"] == "bufete-infante"
    assert cuerpo["email"] == "juan.diego@example.com"

    organizacion = db_session.get(Organizacion, cuerpo["organizacion_id"])
    assert organizacion is not None
    usuario = db_session.get(Usuario, cuerpo["usuario_id"])
    assert usuario is not None
    assert usuario.organizacion_id == organizacion.id

    eventos = (
        db_session.query(EventoAuditoria)
        .filter_by(organizacion_id=organizacion.id)
        .order_by(EventoAuditoria.entidad)
        .all()
    )
    entidades = {evento.entidad for evento in eventos}
    assert entidades == {"organizacion", "usuario"}


def test_registro_con_nombre_repetido_genera_slug_distinto(client):
    primero = _registrar(client, email="uno@example.com").json()
    segundo = _registrar(client, email="dos@example.com").json()
    assert primero["organizacion_slug"] != segundo["organizacion_slug"]


def test_login_correcto_devuelve_token(client):
    registro = _registrar(client).json()

    respuesta = client.post(
        "/v1/auth/login",
        json={
            "organizacion": registro["organizacion_slug"],
            "email": "juan.diego@example.com",
            "contrasena": "clave-larga-1",
        },
    )
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["token_type"] == "bearer"
    assert cuerpo["expira_en_segundos"] == 8 * 3600
    assert cuerpo["access_token"]


def test_login_con_contrasena_incorrecta_devuelve_401(client):
    registro = _registrar(client).json()

    respuesta = client.post(
        "/v1/auth/login",
        json={
            "organizacion": registro["organizacion_slug"],
            "email": "juan.diego@example.com",
            "contrasena": "contrasena-equivocada",
        },
    )
    assert respuesta.status_code == 401


def test_login_con_organizacion_inexistente_devuelve_401(client):
    respuesta = client.post(
        "/v1/auth/login",
        json={"organizacion": "no-existe", "email": "nadie@example.com", "contrasena": "x"},
    )
    assert respuesta.status_code == 401


def _eventos_de_login(db_session, organizacion_id):
    return (
        db_session.query(EventoAuditoria)
        .filter(
            EventoAuditoria.organizacion_id == organizacion_id,
            EventoAuditoria.accion.in_(["login", "login_fallido"]),
        )
        .all()
    )


def test_login_correcto_deja_exactamente_un_evento_de_auditoria(client, db_session):
    """*Quién entró y cuándo* es el evento principal de una plataforma legal
    con un audit log de posible valor probatorio. Hasta ahora un login
    correcto no dejaba rastro en ninguna parte."""
    registro = _registrar(client).json()

    respuesta = client.post(
        "/v1/auth/login",
        json={
            "organizacion": registro["organizacion_slug"],
            "email": "juan.diego@example.com",
            "contrasena": "clave-larga-1",
        },
    )
    assert respuesta.status_code == 200

    eventos = _eventos_de_login(db_session, registro["organizacion_id"])
    assert len(eventos) == 1
    evento = eventos[0]
    assert evento.accion == "login"
    assert evento.entidad == "sesion"
    assert evento.entidad_id is None
    assert str(evento.usuario_id) == registro["usuario_id"]
    assert evento.detalle["ip"]


def test_login_fallido_deja_exactamente_un_evento_con_el_usuario(client, db_session):
    registro = _registrar(client).json()

    respuesta = client.post(
        "/v1/auth/login",
        json={
            "organizacion": registro["organizacion_slug"],
            "email": "juan.diego@example.com",
            "contrasena": "contrasena-equivocada",
        },
    )
    assert respuesta.status_code == 401

    eventos = _eventos_de_login(db_session, registro["organizacion_id"])
    assert len(eventos) == 1
    evento = eventos[0]
    assert evento.accion == "login_fallido"
    assert evento.entidad == "login_fallido"
    # El usuario existe: el evento apunta a él aunque la contraseña fuera mala.
    assert str(evento.usuario_id) == registro["usuario_id"]
    assert evento.detalle["email"] == "juan.diego@example.com"
    assert evento.detalle["ip"]


def test_login_de_un_email_inexistente_deja_evento_sin_usuario(client, db_session):
    """La organización existe, el email no. Hay `organizacion_id` al que
    atribuir el evento, así que se registra — con `usuario_id` NULL, porque
    no hay a quién apuntar. El intento es justo el dato interesante: alguien
    probando correos contra una firma concreta."""
    registro = _registrar(client).json()

    respuesta = client.post(
        "/v1/auth/login",
        json={
            "organizacion": registro["organizacion_slug"],
            "email": "no-trabaja-aqui@example.com",
            "contrasena": "lo-que-sea",
        },
    )
    assert respuesta.status_code == 401

    eventos = _eventos_de_login(db_session, registro["organizacion_id"])
    assert len(eventos) == 1
    assert eventos[0].accion == "login_fallido"
    assert eventos[0].usuario_id is None
    assert eventos[0].detalle["email"] == "no-trabaja-aqui@example.com"


def test_el_detalle_del_audit_log_no_lleva_ni_contrasena_ni_token(client, db_session):
    """Invariante de T4: nunca contraseñas ni tokens en los logs ni en el
    `detalle` de un evento. El audit log es de solo INSERT — lo que entre ahí
    no se puede quitar después."""
    registro = _registrar(client).json()
    contrasena = "clave-larga-1"

    client.post(
        "/v1/auth/login",
        json={
            "organizacion": registro["organizacion_slug"],
            "email": "juan.diego@example.com",
            "contrasena": "contrasena-equivocada",
        },
    )
    token = client.post(
        "/v1/auth/login",
        json={
            "organizacion": registro["organizacion_slug"],
            "email": "juan.diego@example.com",
            "contrasena": contrasena,
        },
    ).json()["access_token"]

    todos = (
        db_session.query(EventoAuditoria)
        .filter_by(organizacion_id=registro["organizacion_id"])
        .all()
    )
    assert todos  # si no hubiera eventos, esta prueba no probaría nada

    for evento in todos:
        texto = json.dumps(evento.detalle or {}, ensure_ascii=False)
        assert contrasena not in texto
        assert "contrasena-equivocada" not in texto
        assert token not in texto


def test_login_supera_rate_limit_devuelve_429_con_auditoria(client, db_session):
    registro = _registrar(client).json()
    slug = registro["organizacion_slug"]

    intento = {"organizacion": slug, "email": "juan.diego@example.com", "contrasena": "mala"}

    for _ in range(rate_limit.LIMITE_INTENTOS):
        respuesta = client.post("/v1/auth/login", json=intento)
        assert respuesta.status_code == 401

    respuesta_bloqueada = client.post("/v1/auth/login", json=intento)
    assert respuesta_bloqueada.status_code == 429

    # Se filtra por `accion` y no por `entidad`: desde que el login fallido
    # deja su propio evento, los dos comparten `entidad="login_fallido"`.
    evento = (
        db_session.query(EventoAuditoria)
        .filter_by(organizacion_id=registro["organizacion_id"], accion="rate_limit_superado")
        .one()
    )
    assert evento.entidad == "login_fallido"
    assert evento.entidad_id is None
    assert evento.detalle["email"] == "juan.diego@example.com"


def test_yo_sin_token_devuelve_401(client):
    respuesta = client.get("/v1/auth/yo")
    assert respuesta.status_code == 401


def test_yo_con_token_devuelve_el_usuario_autenticado(client):
    registro = _registrar(client).json()
    token = client.post(
        "/v1/auth/login",
        json={
            "organizacion": registro["organizacion_slug"],
            "email": "juan.diego@example.com",
            "contrasena": "clave-larga-1",
        },
    ).json()["access_token"]

    respuesta = client.get("/v1/auth/yo", headers={"Authorization": f"Bearer {token}"})
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["usuario_id"] == registro["usuario_id"]
    assert cuerpo["organizacion_id"] == registro["organizacion_id"]
    assert cuerpo["email"] == "juan.diego@example.com"


def test_yo_con_token_invalido_devuelve_401(client):
    respuesta = client.get("/v1/auth/yo", headers={"Authorization": "Bearer token-falso"})
    assert respuesta.status_code == 401
