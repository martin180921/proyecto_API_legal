"""`/v1/auth`: registro, login (camino feliz y error principal), rate-limit
con evento de auditoría, y `/v1/auth/yo`."""
import json
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.api.v1 import auth
from app.core import rate_limit
from app.core.config import settings
from app.core.security import ALGORITMO_JWT, verificar_o_quemar_tiempo
from app.models.evento_auditoria import EventoAuditoria
from app.models.organizacion import Organizacion
from app.models.usuario import Usuario
from app.services import autenticacion


@pytest.fixture(autouse=True)
def _registro_abierto(monkeypatch):
    """`REGISTRO_ABIERTO` es **false** por defecto (ver `app/core/config.py`):
    en F0 el alta la hace `scripts/crear_organizacion.py`, no un endpoint
    público. Casi todas las pruebas de este archivo necesitan registrarse para
    tener con qué hacer login, así que abren el registro a propósito. Las que
    comprueban el comportamiento por defecto lo vuelven a cerrar."""
    monkeypatch.setattr(settings, "registro_abierto", True)


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


def test_registro_cerrado_devuelve_403_sin_tocar_la_base_de_datos(client, db_session, monkeypatch):
    """El comportamiento por defecto. `POST /v1/auth/registro` es público, sin
    límite y ejecuta bcrypt, que es caro por diseño: abierto, cualquiera crea
    organizaciones ilimitadas en la base del piloto y unas pocas peticiones
    concurrentes tumban el único proceso de uvicorn de `railway.json`."""
    monkeypatch.setattr(settings, "registro_abierto", False)
    organizaciones_antes = db_session.query(Organizacion).count()

    respuesta = _registrar(client)

    assert respuesta.status_code == 403
    # Sin efectos: ni organización, ni usuario, ni evento de auditoría.
    assert db_session.query(Organizacion).count() == organizaciones_antes
    assert db_session.query(Usuario).count() == 0
    assert db_session.query(EventoAuditoria).count() == 0


def test_registro_cerrado_no_ejecuta_bcrypt(client, monkeypatch):
    """La mitad cara del arreglo. El 403 tiene que llegar antes del hash: si
    solo cortara después, el endpoint seguiría siendo un amplificador de CPU
    contra un proceso único."""
    monkeypatch.setattr(settings, "registro_abierto", False)

    def _explota(*args, **kwargs):  # pragma: no cover — no debe llamarse
        raise AssertionError("bcrypt no debería ejecutarse con el registro cerrado")

    monkeypatch.setattr("app.api.v1.auth.hash_contrasena", _explota)

    assert _registrar(client).status_code == 403


def test_registro_abierto_sigue_funcionando_igual(client):
    """La otra mitad: abrir el flag devuelve el comportamiento de siempre."""
    respuesta = _registrar(client)
    assert respuesta.status_code == 201
    assert respuesta.json()["organizacion_slug"] == "bufete-infante"


def test_registro_supera_el_rate_limit_por_ip_y_devuelve_429(client):
    """Barato, y cubre el día que el registro se abra: sin esto, «abierto»
    significa ilimitado."""
    for numero in range(rate_limit.LIMITE_INTENTOS):
        respuesta = _registrar(client, email=f"usuario{numero}@example.com")
        assert respuesta.status_code == 201

    bloqueada = _registrar(client, email="uno-mas@example.com")
    assert bloqueada.status_code == 429


def test_colision_de_slug_devuelve_409_y_deja_la_sesion_utilizable(client, db_session, monkeypatch):
    """`_generar_slug_unico` consulta y luego inserta, así que dos registros
    concurrentes con el mismo nombre pueden elegir el mismo slug y chocar
    contra el índice único. Sin capturarlo, el IntegrityError subía sin más:
    500 genérico y sesión inconsistente. Con un solo usuario no pasa nunca; es
    de los defectos que solo aparecen el día que importa.

    Se fuerza parcheando el generador para que devuelva siempre un slug ya
    ocupado, que es la colisión que la concurrencia produciría."""
    primero = _registrar(client, email="primero@example.com").json()
    ocupado = primero["organizacion_slug"]

    generador_real = auth._generar_slug_unico
    monkeypatch.setattr(auth, "_generar_slug_unico", lambda db, nombre: ocupado)

    respuesta = _registrar(client, email="segundo@example.com")
    assert respuesta.status_code == 409

    # La sesión sigue siendo utilizable después de los rollbacks: sin quitar el
    # parche, una consulta cualquiera tiene que funcionar...
    assert db_session.query(Organizacion).filter_by(slug=ocupado).one() is not None

    # ...y restaurando el generador, un registro nuevo vuelve a salir bien. Se
    # restaura solo este parche, no con `monkeypatch.undo()`, que desharía
    # también el de la fixture que abre el registro.
    monkeypatch.setattr(auth, "_generar_slug_unico", generador_real)
    tercero = _registrar(client, nombre_organizacion="Otro Bufete", email="tercero@example.com")
    assert tercero.status_code == 201


def test_generar_slug_unico_agota_los_intentos_y_devuelve_500(client, db_session, monkeypatch):
    """A.3.4: `_generar_slug_unico` era un `while` sin tope — si `token_hex`
    repitiera candidato, el bucle no tenía salida. Se fuerza la colisión
    fijando tanto `_slugify` (mismo `base` siempre) como `secrets.token_hex`
    (mismo sufijo siempre) y pre-creando las dos organizaciones con las que
    va a chocar cada candidato. El bucle debe rendirse en
    `MAXIMO_INTENTOS_SLUG` intentos con un 500, no colgarse."""
    llamadas = []

    def _token_hex_fijo(n):
        llamadas.append(n)
        return "aaaa"

    monkeypatch.setattr(auth, "_slugify", lambda texto: "bufete-fijo")
    monkeypatch.setattr(auth.secrets, "token_hex", _token_hex_fijo)

    db_session.add(Organizacion(nombre="Ya existe", slug="bufete-fijo"))
    db_session.add(Organizacion(nombre="Ya existe también", slug="bufete-fijo-aaaa"))
    db_session.commit()

    respuesta = _registrar(client, nombre_organizacion="Cualquiera")

    assert respuesta.status_code == 500
    # Un candidato generado por intento agotado, ni uno más: es la prueba de
    # que el bucle termina en el tope y no sigue reintentando indefinidamente.
    assert len(llamadas) == auth.MAXIMO_INTENTOS_SLUG


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


def test_veinte_intentos_contra_slug_inexistente_desde_la_misma_ip_devuelve_429_en_el_veintiuno(client):
    """Escenario de enumeración. Antes del Bloque A1 (A.1.2), el camino de
    organización inexistente no consumía ningún rate-limit: se rechazaba con
    un SELECT sin tocar ningún contador, así que la enumeración de slugs era
    ilimitada. La clave global `login:ip:{ip}` cierra ese hueco con su propio
    umbral (`LIMITE_INTENTOS_IP_GLOBAL`, Bloque A1 bis, 2026-08-16), más alto
    que el de las claves por-organización porque es un tope de enumeración,
    no la defensa contra fuerza bruta de una cuenta concreta.

    Lo que prueba este test es que el endpoint bloquea en el umbral
    configurado, no que bcrypt corre veinte veces contra el hash señuelo
    (eso ya lo prueba
    `test_verificar_o_quemar_tiempo_y_su_uso_en_organizacion_inexistente`). Por
    eso se ceba el contador llamando directamente a `registrar_intento` en vez
    de hacer 20 peticiones HTTP reales, y solo se hacen las dos que importan:
    la 20 (401) y la 21 (429). Acopla la prueba al formato interno de la clave
    (`login:ip:{ip}`, definido en `intentar_login`) — acoplamiento aceptado a
    propósito, igual que la nota de A2 sobre esta misma prueba."""
    intento = {"organizacion": "no-existe", "email": "nadie@example.com", "contrasena": "x"}
    ip = "testclient"  # lo que expone request.client.host en TestClient

    for _ in range(rate_limit.LIMITE_INTENTOS_IP_GLOBAL - 1):
        rate_limit.registrar_intento(f"login:ip:{ip}")

    respuesta = client.post("/v1/auth/login", json=intento)
    assert respuesta.status_code == 401

    bloqueada = client.post("/v1/auth/login", json=intento)
    assert bloqueada.status_code == 429


def test_login_correcto_tras_fallos_contra_slug_inexistente_limpia_el_contador_global_por_ip(client):
    """Un acierto borra también la clave global por IP, igual que ya hacía con
    las claves por-organización (arreglo 8 del 2026-08-08).

    Se construye la cuenta hasta un fallo por debajo del umbral global
    (`LIMITE_INTENTOS_IP_GLOBAL - 1`) fallando contra un slug inexistente —así
    no se toca ninguna clave por-organización—, se hace un login correcto en
    una organización real, y se comprueban dos fallos más contra el slug
    inexistente. Sin el reinicio, el primero de esos dos completaría el
    contador viejo (`19 + 1 = 20`) y el segundo toparía con el 429; con el
    reinicio, los dos siguen devolviendo 401 porque el contador vuelve a
    empezar de cero."""
    intento_slug_inexistente = {
        "organizacion": "no-existe",
        "email": "nadie@example.com",
        "contrasena": "x",
    }

    for _ in range(rate_limit.LIMITE_INTENTOS_IP_GLOBAL - 1):
        assert client.post("/v1/auth/login", json=intento_slug_inexistente).status_code == 401

    registro = _registrar(client).json()
    correcto = client.post(
        "/v1/auth/login",
        json={
            "organizacion": registro["organizacion_slug"],
            "email": "juan.diego@example.com",
            "contrasena": "clave-larga-1",
        },
    )
    assert correcto.status_code == 200

    for _ in range(2):
        assert client.post("/v1/auth/login", json=intento_slug_inexistente).status_code == 401


def test_verificar_o_quemar_tiempo_y_su_uso_en_organizacion_inexistente(client, monkeypatch):
    """El hash señuelo se usa: `verificar_o_quemar_tiempo(x, None)` siempre
    devuelve `False`, y el camino de organización inexistente lo invoca — así
    el coste de esa organización es el mismo que el de una contraseña mala
    (A.1.2). Se comprueba con un espía, no midiendo tiempos: son frágiles en
    CI."""
    assert verificar_o_quemar_tiempo("cualquier-cosa", None) is False

    llamadas = []
    original = autenticacion.verificar_o_quemar_tiempo

    def _espia(contrasena, contrasena_hash):
        llamadas.append(contrasena_hash)
        return original(contrasena, contrasena_hash)

    monkeypatch.setattr(autenticacion, "verificar_o_quemar_tiempo", _espia)

    respuesta = client.post(
        "/v1/auth/login",
        json={"organizacion": "no-existe", "email": "nadie@example.com", "contrasena": "x"},
    )
    assert respuesta.status_code == 401
    assert llamadas == [None]


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


def test_el_evento_de_login_fallido_lleva_el_request_id_de_su_respuesta(client, db_session):
    """A.3.3 (Bloque A2): el `request_id` que el middleware pone en la
    cabecera `X-Request-ID` es el mismo que `registrar` añade a `detalle` vía
    el `ContextVar` de `app/core/contexto.py`. Es la prueba que atrapa una
    propagación de `contextvars` rota — si el middleware fijara el valor
    dentro de una tarea que Starlette no comparte con el endpoint, esta
    aserción fallaría aunque `X-Request-ID` siguiera presente en la cabecera."""
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
    request_id = respuesta.headers["X-Request-ID"]
    assert request_id

    eventos = _eventos_de_login(db_session, registro["organizacion_id"])
    assert len(eventos) == 1
    assert eventos[0].detalle["request_id"] == request_id


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


def _ip_del_evento_de_login_fallido(client, db_session, registro, cabeceras=None):
    """Provoca un login fallido y devuelve la IP que quedó en el audit log.

    El `detalle` del evento es la forma de observar qué IP resolvió el helper
    sin llamarlo directamente: es la misma que alimenta la clave del
    rate-limit, así que probar una prueba las dos."""
    client.post(
        "/v1/auth/login",
        json={
            "organizacion": registro["organizacion_slug"],
            "email": "juan.diego@example.com",
            "contrasena": "contrasena-equivocada",
        },
        headers=cabeceras or {},
    )
    evento = (
        db_session.query(EventoAuditoria)
        .filter_by(organizacion_id=registro["organizacion_id"], accion="login_fallido")
        .one()
    )
    return evento.detalle["ip"]


def test_en_produccion_se_usa_la_ip_de_x_forwarded_for(client, db_session, monkeypatch):
    """Sin esto, `request.client.host` devuelve la IP del edge de Railway: la
    clave del rate-limit se colapsa en una sola por organización y 5 fallos de
    cualquiera dejan fuera a toda la firma 15 minutos."""
    monkeypatch.setattr(settings, "app_env", "production")
    registro = _registrar(client).json()

    ip = _ip_del_evento_de_login_fallido(
        client, db_session, registro, {"X-Forwarded-For": "203.0.113.7"}
    )
    assert ip == "203.0.113.7"


def test_con_varios_valores_en_x_forwarded_for_se_toma_el_primero(client, db_session, monkeypatch):
    """El proxy añade por la derecha, así que el cliente original es el de más
    a la izquierda."""
    monkeypatch.setattr(settings, "app_env", "production")
    registro = _registrar(client).json()

    ip = _ip_del_evento_de_login_fallido(
        client,
        db_session,
        registro,
        {"X-Forwarded-For": "203.0.113.7, 70.41.3.18, 150.172.238.178"},
    )
    assert ip == "203.0.113.7"


@pytest.mark.parametrize(
    "cabeceras",
    [
        {},  # la cabecera no llega
        {"X-Forwarded-For": "no-es-una-ip"},  # llega con basura
        {"X-Forwarded-For": ""},  # llega vacía
    ],
)
def test_sin_x_forwarded_for_valida_se_cae_a_la_ip_directa(client, db_session, monkeypatch, cabeceras):
    """Se valida además de recortar: sin esto entraría texto arbitrario de la
    petición en una clave de rate-limit y en el `detalle` del audit log."""
    monkeypatch.setattr(settings, "app_env", "production")
    registro = _registrar(client).json()

    ip = _ip_del_evento_de_login_fallido(client, db_session, registro, cabeceras)
    assert ip == "testclient"  # lo que expone request.client.host en TestClient


def test_fuera_de_produccion_se_ignora_x_forwarded_for(client, db_session, monkeypatch):
    """En local y en CI no hay proxy delante, así que esa cabecera solo puede
    venir de quien hace la petición: confiar en ella sería regalarle la
    capacidad de elegir su propia clave de rate-limit."""
    monkeypatch.setattr(settings, "app_env", "local")
    registro = _registrar(client).json()

    ip = _ip_del_evento_de_login_fallido(
        client, db_session, registro, {"X-Forwarded-For": "203.0.113.7"}
    )
    assert ip == "testclient"


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


def test_login_supera_rate_limit_por_organizacion_devuelve_429_con_auditoria(client, db_session):
    """Escenario de fuerza bruta contra una organización real, desde una sola
    IP. Con la clave global en su propio umbral, más alto que el de
    organización (Bloque A1 bis, 2026-08-16: `LIMITE_INTENTOS_IP_GLOBAL=20` vs
    `LIMITE_INTENTOS=5`), la clave por-organización (`clave_usuario`/
    `clave_ip`) vuelve a ser la primera en dispararse en este ataque —el más
    común en la práctica—, y vuelve a dejar su evento `rate_limit_superado`
    con `organizacion_id`. Antes de este commit, la clave global (entonces con
    el mismo umbral que la de organización) se disparaba primero y este
    evento no se generaba; ver `cc3a773` y la nota de sesión de Bloque A1
    bis."""
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


def test_insistir_tras_el_bloqueo_no_multiplica_los_eventos(client, db_session):
    """El rate-limit no puede ser un amplificador de escrituras.

    Antes, cada petición bloqueada escribía una fila en `eventos_auditoria`:
    quien insistiera generaba escrituras ilimitadas en la única tabla que por
    diseño no se puede borrar. Lo auditable es la transición —esta clave se ha
    bloqueado—, no cada rebote posterior."""
    registro = _registrar(client).json()
    intento = {
        "organizacion": registro["organizacion_slug"],
        "email": "juan.diego@example.com",
        "contrasena": "mala",
    }

    for _ in range(rate_limit.LIMITE_INTENTOS):
        assert client.post("/v1/auth/login", json=intento).status_code == 401

    for _ in range(10):
        assert client.post("/v1/auth/login", json=intento).status_code == 429

    eventos = (
        db_session.query(EventoAuditoria)
        .filter_by(organizacion_id=registro["organizacion_id"], accion="rate_limit_superado")
        .all()
    )
    assert len(eventos) == 1


def test_un_login_correcto_reinicia_el_contador_de_fallos(client):
    """Cuatro fallos, un acierto, y cuatro fallos más: el usuario sigue
    recibiendo 401, no 429. Sin esto, un acierto no contaba para nada y el
    usuario quedaba a un solo fallo del bloqueo durante el resto de la
    ventana."""
    registro = _registrar(client).json()
    fallido = {
        "organizacion": registro["organizacion_slug"],
        "email": "juan.diego@example.com",
        "contrasena": "mala",
    }
    correcto = {**fallido, "contrasena": "clave-larga-1"}

    for _ in range(rate_limit.LIMITE_INTENTOS - 1):
        assert client.post("/v1/auth/login", json=fallido).status_code == 401

    assert client.post("/v1/auth/login", json=correcto).status_code == 200

    for _ in range(rate_limit.LIMITE_INTENTOS - 1):
        assert client.post("/v1/auth/login", json=fallido).status_code == 401


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


def _forjar_token(usuario_id, organizacion_id):
    """Firma un JWT con el mismo `SECRET_KEY` y el mismo algoritmo que
    `crear_token_sesion` (`app/core/security.py`), pero con `sub` y `org`
    elegidos a mano en vez de sacados de una sesión real. No es un esquema de
    firma nuevo: es el mismo token, con claims fabricados para probar qué pasa
    si no coinciden entre sí."""
    ahora = datetime.now(timezone.utc)
    claims = {
        "sub": str(usuario_id),
        "org": str(organizacion_id),
        "exp": ahora + timedelta(hours=8),
    }
    return jwt.encode(claims, settings.secret_key, algorithm=ALGORITMO_JWT)


def test_token_con_organizacion_distinta_a_la_del_usuario_devuelve_401(client):
    """Prueba cruzada de tenancy (parada P2): un token no sirve fuera de su
    organización. `GET /v1/auth/yo` es hoy la única superficie que lee datos
    de un usuario autenticado, así que es el sitio natural donde crecerán las
    pruebas de tenancy cuando la Etapa Entrada añada más endpoints que lean
    datos de negocio."""
    organizacion_a = _registrar(client, nombre_organizacion="Bufete A", email="a@example.com").json()
    organizacion_b = _registrar(client, nombre_organizacion="Bufete B", email="b@example.com").json()

    token_cruzado = _forjar_token(
        usuario_id=organizacion_a["usuario_id"],
        organizacion_id=organizacion_b["organizacion_id"],
    )

    respuesta = client.get("/v1/auth/yo", headers={"Authorization": f"Bearer {token_cruzado}"})
    assert respuesta.status_code == 401
