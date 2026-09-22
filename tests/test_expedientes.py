"""`/v1/expedientes`: camino feliz y error principal de cada endpoint,
validación del identificador, y prueba cruzada de tenancy (parada P3)."""
import uuid

import pytest

from app.core.config import settings
from app.models.evento_auditoria import EventoAuditoria
from app.models.expediente import Expediente
from app.models.usuario import Usuario

IDENTIFICADOR_VALIDO = "12345678901234567890123"
IDENTIFICADOR_VALIDO_2 = "98765432109876543210987"


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


def _payload(identificador=IDENTIFICADOR_VALIDO, **overrides):
    payload = {
        "identificador": identificador,
        "tipo_identificador": "radicado_unificado",
        "seguimiento": "automatico",
        "juzgado": "Juzgado Primero Civil del Circuito",
        "despacho": "Despacho 001",
        "partes": "Demandante vs Demandado",
        "tipo_proceso": "civil",
        "ultima_actuacion_al_importar": "Auto admisorio",
    }
    payload.update(overrides)
    return payload


# --- POST /v1/expedientes -----------------------------------------------


def test_crear_expediente_devuelve_201_con_auditoria(client, db_session):
    _, cabeceras = _registrar_y_loguear(client)

    respuesta = client.post("/v1/expedientes", json=_payload(), headers=cabeceras)

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["identificador"] == IDENTIFICADOR_VALIDO
    assert cuerpo["tipo_identificador"] == "radicado_unificado"
    assert cuerpo["seguimiento"] == "automatico"
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
    "identificador",
    [
        "123",  # demasiado corto
        "1234567890123456789012a",  # no numérico
        "123456789012345678901234",  # 24 dígitos, uno de más
        "1234567890123456789012",  # 22 dígitos, uno de menos
    ],
)
def test_crear_expediente_radicado_unificado_con_identificador_invalido_devuelve_422(client, identificador):
    """B.1: la CHECK de 23 dígitos sigue vigente para `radicado_unificado`."""
    _, cabeceras = _registrar_y_loguear(client)

    respuesta = client.post(
        "/v1/expedientes", json=_payload(identificador=identificador), headers=cabeceras
    )

    assert respuesta.status_code == 422


def test_crear_expediente_sin_radicar_no_exige_23_digitos(client):
    """B.1: el eslabón roto que la revisión del 2026-08-16 marcó como el
    hallazgo más importante — la fila 81 del Excel de Juan Diego (demanda
    todavía sin radicar) tiene que caber en el modelo."""
    _, cabeceras = _registrar_y_loguear(client)

    respuesta = client.post(
        "/v1/expedientes",
        json=_payload(
            identificador="fila-81-sin-radicar-todavia",
            tipo_identificador="sin_radicar",
            seguimiento="manual",
            tipo_proceso="administrativo",
        ),
        headers=cabeceras,
    )

    assert respuesta.status_code == 201
    assert respuesta.json()["tipo_identificador"] == "sin_radicar"


def test_crear_expediente_expediente_contraloria_como_seguimiento_manual(client):
    """B.1: Contraloría entra como seguimiento manual, sin radicado de Rama
    Judicial — la decisión de alcance que desbloquea este bloque."""
    _, cabeceras = _registrar_y_loguear(client)

    respuesta = client.post(
        "/v1/expedientes",
        json=_payload(
            identificador="responsabilidad-fiscal-001",
            tipo_identificador="expediente_contraloria",
            seguimiento="manual",
            tipo_proceso="administrativo",
        ),
        headers=cabeceras,
    )

    assert respuesta.status_code == 201


def test_crear_expediente_con_partes_de_10000_caracteres_pasa(client):
    """Cota exacta (A.3.6): 10.000 caracteres, el límite mismo, sigue
    aceptándose."""
    _, cabeceras = _registrar_y_loguear(client)

    respuesta = client.post(
        "/v1/expedientes", json=_payload(partes="x" * 10_000), headers=cabeceras
    )

    assert respuesta.status_code == 201


@pytest.mark.parametrize("campo", ["partes", "ultima_actuacion_al_importar"])
def test_crear_expediente_con_texto_de_10001_caracteres_devuelve_422(client, campo):
    """A.3.6: `partes` y `ultima_actuacion_al_importar` eran `Text` sin
    `max_length` ni en Pydantic ni en la base — entrada no acotada que un
    usuario autenticado podía llenar con megabytes. El tope vive en la
    frontera de la aplicación (Pydantic); la columna `Text` de Postgres no
    cambia."""
    _, cabeceras = _registrar_y_loguear(client)

    respuesta = client.post(
        "/v1/expedientes", json=_payload(**{campo: "x" * 10_001}), headers=cabeceras
    )

    assert respuesta.status_code == 422


def test_crear_expediente_con_identificador_duplicado_en_la_misma_organizacion_devuelve_409(client):
    _, cabeceras = _registrar_y_loguear(client)
    assert client.post("/v1/expedientes", json=_payload(), headers=cabeceras).status_code == 201

    respuesta = client.post("/v1/expedientes", json=_payload(), headers=cabeceras)

    assert respuesta.status_code == 409


def test_mismo_identificador_en_organizaciones_distintas_no_choca(client):
    """El identificador es único por organización, no global."""
    _, cabeceras_a = _registrar_y_loguear(client, nombre_organizacion="Bufete A", email="a@example.com")
    _, cabeceras_b = _registrar_y_loguear(client, nombre_organizacion="Bufete B", email="b@example.com")

    assert client.post("/v1/expedientes", json=_payload(), headers=cabeceras_a).status_code == 201
    assert client.post("/v1/expedientes", json=_payload(), headers=cabeceras_b).status_code == 201


# --- B.1-bis / A5.3: procesos_fuente sustituye los campos del conector -----


def test_expediente_recien_creado_tiene_procesos_vacio(client):
    """Los tres campos del motor (`id_proceso_rama`, `fecha_ultima_consulta`,
    `ultimo_consecutivo_visto`) salieron de `Expediente` en A5.3 (B.1-bis,
    2026-09-22): el estado del motor vive en `procesos_fuente`, y un
    expediente recién creado todavía no tiene ninguno."""
    _, cabeceras = _registrar_y_loguear(client)

    cuerpo = client.post("/v1/expedientes", json=_payload(), headers=cabeceras).json()

    assert cuerpo["procesos"] == []
    assert "id_proceso_rama" not in cuerpo
    assert "fecha_ultima_consulta" not in cuerpo
    assert "ultimo_consecutivo_visto" not in cuerpo


def test_patch_con_campo_del_motor_desconocido_devuelve_422(client):
    """R.4 + `extra=\"forbid\"` (A5.3, decisión de Martin, 2026-09-22): los
    tres campos que escribía el motor ya no existen en `ExpedienteActualizar`
    — un PATCH que los traiga da 422 en vez de ignorarlos en silencio."""
    _, cabeceras = _registrar_y_loguear(client)
    creado = client.post("/v1/expedientes", json=_payload(), headers=cabeceras).json()

    respuesta = client.patch(
        f"/v1/expedientes/{creado['id']}",
        json={"ultimo_consecutivo_visto": 55},
        headers=cabeceras,
    )

    assert respuesta.status_code == 422


def test_patch_con_campo_desconocido_cualquiera_devuelve_422(client):
    """`extra=\"forbid\"` no es solo para los tres campos del motor: cierra
    la vía para cualquier campo mal escrito o inventado."""
    _, cabeceras = _registrar_y_loguear(client)
    creado = client.post("/v1/expedientes", json=_payload(), headers=cabeceras).json()

    respuesta = client.patch(
        f"/v1/expedientes/{creado['id']}",
        json={"despcaho": "typo"},
        headers=cabeceras,
    )

    assert respuesta.status_code == 422


# --- GET /v1/expedientes (paginado) --------------------------------------


def test_listar_expedientes_devuelve_solo_los_de_la_organizacion_del_actor(client):
    _, cabeceras_a = _registrar_y_loguear(client, nombre_organizacion="Bufete A", email="a@example.com")
    _, cabeceras_b = _registrar_y_loguear(client, nombre_organizacion="Bufete B", email="b@example.com")

    client.post("/v1/expedientes", json=_payload(), headers=cabeceras_a)
    client.post("/v1/expedientes", json=_payload(identificador=IDENTIFICADOR_VALIDO_2), headers=cabeceras_a)
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
            json=_payload(identificador=f"1000000000000000000000{indice}"),
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
        json={"despacho": "Despacho 002", "ultima_actuacion_al_importar": "Traslado"},
        headers=cabeceras,
    )

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["despacho"] == "Despacho 002"
    assert cuerpo["ultima_actuacion_al_importar"] == "Traslado"
    # Lo no enviado no cambia.
    assert cuerpo["identificador"] == IDENTIFICADOR_VALIDO

    evento = (
        db_session.query(EventoAuditoria)
        .filter_by(entidad="expediente", entidad_id=creado["id"], accion="actualizar")
        .one()
    )
    assert set(evento.detalle["campos"]) == {"despacho", "ultima_actuacion_al_importar"}


def test_actualizar_expediente_inexistente_devuelve_404(client):
    _, cabeceras = _registrar_y_loguear(client)

    respuesta = client.patch(
        "/v1/expedientes/00000000-0000-0000-0000-000000000000",
        json={"despacho": "Despacho 002"},
        headers=cabeceras,
    )

    assert respuesta.status_code == 404


def test_actualizar_expediente_con_identificador_invalido_devuelve_422(client):
    """Cuando el PATCH trae `tipo_identificador` e `identificador` a la vez
    (el caso de corregir la fila 18/34 cuando Juan Diego confirme el dato),
    se valida la combinación igual que en la creación."""
    _, cabeceras = _registrar_y_loguear(client)
    creado = client.post("/v1/expedientes", json=_payload(), headers=cabeceras).json()

    respuesta = client.patch(
        f"/v1/expedientes/{creado['id']}",
        json={"tipo_identificador": "radicado_unificado", "identificador": "123"},
        headers=cabeceras,
    )

    assert respuesta.status_code == 422


def test_actualizar_solo_tipo_identificador_que_viola_la_check_devuelve_422(client):
    """Revisión P4 (2026-08-22): cuando el PATCH trae solo `tipo_identificador`,
    Pydantic no puede validar la combinación (no conoce el identificador
    vigente) y quien la atrapa es la CHECK de la base de datos (SQLSTATE
    23514). Antes ese IntegrityError se respondía como si fuera el UNIQUE:
    409 con el mensaje de duplicado — engañoso. Ahora es 422 con el mismo
    texto del validador."""
    _, cabeceras = _registrar_y_loguear(client)
    creado = client.post(
        "/v1/expedientes",
        json=_payload(identificador="EXP-2026-001", tipo_identificador="sin_radicar"),
        headers=cabeceras,
    ).json()

    respuesta = client.patch(
        f"/v1/expedientes/{creado['id']}",
        json={"tipo_identificador": "radicado_unificado"},
        headers=cabeceras,
    )

    assert respuesta.status_code == 422
    assert respuesta.json()["detail"] == (
        "Con tipo_identificador='radicado_unificado' el identificador debe "
        "tener exactamente 23 dígitos"
    )


# --- A.2.4: responsable_usuario_id ----------------------------------------


def test_crear_expediente_sin_responsable_es_valido(client):
    _, cabeceras = _registrar_y_loguear(client)

    respuesta = client.post("/v1/expedientes", json=_payload(), headers=cabeceras)

    assert respuesta.status_code == 201
    assert respuesta.json()["responsable_usuario_id"] is None


def test_patch_asigna_responsable(client, db_session):
    registro, cabeceras = _registrar_y_loguear(client)
    creado = client.post("/v1/expedientes", json=_payload(), headers=cabeceras).json()
    usuario_id = registro["usuario_id"]

    respuesta = client.patch(
        f"/v1/expedientes/{creado['id']}",
        json={"responsable_usuario_id": usuario_id},
        headers=cabeceras,
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["responsable_usuario_id"] == usuario_id


def test_crear_expediente_con_responsable_de_otra_organizacion_devuelve_422_y_no_escribe(
    client, db_session
):
    """R.3 (revisión del 2026-09-17): antes de A5.3 un `responsable_usuario_id`
    de otra organización violaba la FK simple con un `IntegrityError` que el
    router traducía, por error, en 409 «ya existe un expediente con ese
    identificador» — un mensaje falso. Ahora se valida antes de escribir."""
    _, cabeceras_a = _registrar_y_loguear(client, nombre_organizacion="Bufete A", email="a@example.com")
    registro_b, _ = _registrar_y_loguear(client, nombre_organizacion="Bufete B", email="b@example.com")

    respuesta = client.post(
        "/v1/expedientes",
        json=_payload(responsable_usuario_id=registro_b["usuario_id"]),
        headers=cabeceras_a,
    )

    assert respuesta.status_code == 422
    assert respuesta.json()["detail"]["codigo"] == "responsable_invalido"
    assert (
        db_session.query(Expediente)
        .filter_by(identificador=IDENTIFICADOR_VALIDO)
        .first()
        is None
    )


def test_patch_con_responsable_de_otra_organizacion_devuelve_422(client):
    _, cabeceras_a = _registrar_y_loguear(client, nombre_organizacion="Bufete A", email="a@example.com")
    registro_b, _ = _registrar_y_loguear(client, nombre_organizacion="Bufete B", email="b@example.com")
    creado = client.post("/v1/expedientes", json=_payload(), headers=cabeceras_a).json()

    respuesta = client.patch(
        f"/v1/expedientes/{creado['id']}",
        json={"responsable_usuario_id": registro_b["usuario_id"]},
        headers=cabeceras_a,
    )

    assert respuesta.status_code == 422
    assert respuesta.json()["detail"]["codigo"] == "responsable_invalido"


def test_patch_con_responsable_inactivo_de_la_misma_organizacion_devuelve_422(client, db_session):
    registro, cabeceras = _registrar_y_loguear(client)
    creado = client.post("/v1/expedientes", json=_payload(), headers=cabeceras).json()

    otro_usuario = Usuario(
        organizacion_id=uuid.UUID(registro["organizacion_id"]),
        email="inactivo@example.com",
        nombre="Usuario Inactivo",
        contrasena_hash="x",
        activo=False,
    )
    db_session.add(otro_usuario)
    db_session.flush()
    db_session.commit()

    respuesta = client.patch(
        f"/v1/expedientes/{creado['id']}",
        json={"responsable_usuario_id": str(otro_usuario.id)},
        headers=cabeceras,
    )

    assert respuesta.status_code == 422
    assert respuesta.json()["detail"]["codigo"] == "responsable_invalido"


def test_parte_con_organizacion_distinta_a_la_de_su_expediente_viola_fk_compuesta(
    db_session,
):
    """R.3, capa de base de datos: la prueba que de verdad cierra el
    invariante de tenancy, insertando por SQLAlchemy Core (sin pasar por el
    servicio) una `Parte` cuyo `organizacion_id` no coincide con el de su
    `expediente_id`. La FK compuesta `(organizacion_id, expediente_id) ->
    expedientes (organizacion_id, id)` (A5.3) hace que la base la rechace,
    algo que la FK simple anterior no podía impedir."""
    from sqlalchemy.exc import IntegrityError as SAIntegrityError

    from app.models.organizacion import Organizacion

    organizacion_a = Organizacion(nombre="Bufete A", slug="bufete-a-fk")
    organizacion_b = Organizacion(nombre="Bufete B", slug="bufete-b-fk")
    db_session.add_all([organizacion_a, organizacion_b])
    db_session.flush()

    expediente_a = Expediente(
        organizacion_id=organizacion_a.id,
        identificador=IDENTIFICADOR_VALIDO,
        tipo_identificador="radicado_unificado",
        seguimiento="automatico",
        tipo_proceso="civil",
    )
    db_session.add(expediente_a)
    db_session.flush()

    from app.models.parte import Parte

    parte_de_otra_organizacion = Parte(
        organizacion_id=organizacion_b.id,  # distinto al de expediente_a
        expediente_id=expediente_a.id,
        tipo="Demandante",
        nombre="Alguien",
        origen="importacion",
    )
    db_session.add(parte_de_otra_organizacion)

    with pytest.raises(SAIntegrityError):
        db_session.flush()


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


# --- A.1.3 / A5.1: revalidación del actor, en mutación y en lectura --------


def test_patch_con_usuario_desactivado_devuelve_401_aunque_el_jwt_siga_valido(client, db_session):
    registro, cabeceras = _registrar_y_loguear(client)
    creado = client.post("/v1/expedientes", json=_payload(), headers=cabeceras).json()

    usuario = db_session.get(Usuario, uuid.UUID(registro["usuario_id"]))
    usuario.activo = False
    db_session.flush()

    respuesta = client.patch(
        f"/v1/expedientes/{creado['id']}", json={"despacho": "otro"}, headers=cabeceras
    )

    assert respuesta.status_code == 401


def test_get_con_usuario_desactivado_devuelve_401(client, db_session):
    """Decisión revisada el 2026-09-22 (A5.1, Martin): las rutas de solo
    lectura pasan también a `usuario_actual_verificado`. Hasta entonces se
    quedaban con `usuario_actual` (sin SELECT extra) y un usuario desactivado
    seguía leyendo con un JWT ya emitido hasta que expirara (hasta 8h) — el
    hallazgo R.2 de la revisión integral del 2026-09-17."""
    registro, cabeceras = _registrar_y_loguear(client)
    creado = client.post("/v1/expedientes", json=_payload(), headers=cabeceras).json()

    usuario = db_session.get(Usuario, uuid.UUID(registro["usuario_id"]))
    usuario.activo = False
    db_session.flush()
    db_session.commit()

    respuesta = client.get(f"/v1/expedientes/{creado['id']}", headers=cabeceras)

    assert respuesta.status_code == 401


def test_listar_con_usuario_desactivado_devuelve_401(client, db_session):
    registro, cabeceras = _registrar_y_loguear(client)
    client.post("/v1/expedientes", json=_payload(), headers=cabeceras)

    usuario = db_session.get(Usuario, uuid.UUID(registro["usuario_id"]))
    usuario.activo = False
    db_session.flush()
    db_session.commit()

    respuesta = client.get("/v1/expedientes", headers=cabeceras)

    assert respuesta.status_code == 401
