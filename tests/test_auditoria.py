"""Audit log inmutable: cada mutación deja un evento y no hay código de
actualización/borrado sobre `eventos_auditoria`
([[Multi-tenancy y audit log desde el día 1]])."""
import inspect
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.models.evento_auditoria import EventoAuditoria
from app.models.organizacion import Organizacion
from app.models.usuario import Usuario
from app.services import auditoria


def _crear_org_y_usuario(db_session):
    org = Organizacion(nombre="Bufete Infante", slug="bufete-infante")
    db_session.add(org)
    db_session.flush()
    usuario = Usuario(organizacion_id=org.id, email="juan.diego@example.com", contrasena_hash="x")
    db_session.add(usuario)
    db_session.flush()
    return org, usuario


def test_mutacion_deja_evento_de_auditoria(db_session):
    org, usuario = _crear_org_y_usuario(db_session)

    usuario.contrasena_hash = "nuevo-hash"
    auditoria.registrar(
        db_session,
        organizacion_id=org.id,
        accion="actualizar_contrasena",
        entidad="usuario",
        entidad_id=usuario.id,
        usuario_id=usuario.id,
        detalle={"campo": "contrasena_hash"},
    )
    db_session.flush()

    evento = db_session.query(EventoAuditoria).one()
    assert evento.organizacion_id == org.id
    assert evento.usuario_id == usuario.id
    assert evento.accion == "actualizar_contrasena"
    assert evento.entidad == "usuario"
    assert evento.entidad_id == usuario.id
    assert evento.detalle == {"campo": "contrasena_hash"}
    assert evento.creado_en is not None


def test_registrar_sin_usuario_admite_accion_del_sistema(db_session):
    org, _ = _crear_org_y_usuario(db_session)

    evento = auditoria.registrar(
        db_session,
        organizacion_id=org.id,
        accion="importar_excel",
        entidad="expediente",
        entidad_id=uuid.uuid4(),
    )
    db_session.flush()

    assert evento.usuario_id is None
    assert evento.detalle is None


def test_registrar_sin_entidad_id_admite_evento_sin_fila(db_session):
    """El caso que fuerza que `entidad_id` sea nullable: un rate-limit de
    login por IP (T4) es auditable pero no apunta a ninguna fila. El evento
    conserva su tipo en `entidad`, que sigue siendo obligatorio."""
    org, _ = _crear_org_y_usuario(db_session)

    evento = auditoria.registrar(
        db_session,
        organizacion_id=org.id,
        accion="rate_limit_superado",
        entidad="login_fallido",
        detalle={"ip": "203.0.113.7", "intentos": 6},
    )
    db_session.flush()

    assert evento.entidad_id is None
    assert evento.entidad == "login_fallido"


def test_servicio_auditoria_solo_expone_registrar():
    """Ninguna función de actualización o borrado en el módulo: la única
    vía de escritura del audit log es `registrar` (INSERT)."""
    funciones = [
        nombre
        for nombre, obj in inspect.getmembers(auditoria, inspect.isfunction)
        if obj.__module__ == auditoria.__name__
    ]
    assert funciones == ["registrar"]


def test_modelo_no_define_campos_de_actualizacion():
    columnas = {c.name for c in EventoAuditoria.__table__.columns}
    assert columnas == {
        "id",
        "creado_en",
        "organizacion_id",
        "usuario_id",
        "accion",
        "entidad",
        "entidad_id",
        "detalle",
    }


def test_el_rol_de_pruebas_no_es_superusuario(db_session):
    """Guarda de las dos pruebas de abajo. Un superusuario de Postgres se
    salta todos los GRANT/REVOKE sin avisar: si la suite corriera con uno,
    la prueba del REVOKE pasaría en verde sin comprobar nada.

    Verificado contra Postgres 16 el 2026-08-05: como superusuario, el
    `UPDATE` sobre `eventos_auditoria` se ejecuta sin error pese al REVOKE."""
    es_superusuario = db_session.execute(
        text("select usesuper from pg_user where usename = current_user")
    ).scalar()
    assert es_superusuario is False, (
        "La base de datos de pruebas está conectada con un superusuario, que ignora "
        "el REVOKE del audit log. Usa el rol `api_legal_app` (ver docker-compose.yml)."
    )


def test_revoke_impide_update_y_delete_del_audit_log(db_session):
    """La inmutabilidad de código no basta: el REVOKE de la migración tiene
    que bloquear de verdad. Antes esto solo se comprobaba leyendo el texto de
    la migración, porque la suite corría sobre SQLite, que no tiene modelo de
    permisos. Ahora se ejecuta contra Postgres."""
    org, _ = _crear_org_y_usuario(db_session)
    auditoria.registrar(
        db_session,
        organizacion_id=org.id,
        accion="crear",
        entidad="organizacion",
        entidad_id=org.id,
    )
    db_session.flush()

    # TRUNCATE está en la lista a propósito: en Postgres es un permiso
    # distinto de DELETE, y revocar solo UPDATE/DELETE dejaba abierta la vía
    # de vaciar el audit log entero de un golpe.
    for sentencia in (
        "update eventos_auditoria set accion = 'falsificado'",
        "delete from eventos_auditoria",
        "truncate eventos_auditoria",
    ):
        with pytest.raises(ProgrammingError) as error:
            db_session.execute(text(sentencia))
        assert "permission denied" in str(error.value).lower()
        db_session.rollback()


def test_la_migracion_documenta_el_limite_del_revoke():
    """El REVOKE bloquea al rol de la app, pero ese rol es owner de la tabla
    y puede volver a concederse los permisos — y si el rol fuera superusuario
    (el que da Railway por defecto), el REVOKE no haría nada en absoluto.
    Mientras eso siga así, la limitación tiene que estar escrita al lado del
    REVOKE: si alguien borra la anotación, este test lo detiene."""
    versions_dir = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    migraciones = list(versions_dir.glob("*audit_log_inmutable*.py"))
    assert len(migraciones) == 1

    contenido = migraciones[0].read_text(encoding="utf-8")
    assert "REVOKE UPDATE, DELETE, TRUNCATE ON eventos_auditoria FROM CURRENT_USER" in contenido
    assert "RIESGO RESIDUAL ACEPTADO" in contenido
