"""Audit log inmutable: cada mutación deja un evento y no hay código de
actualización/borrado sobre `eventos_auditoria`
([[Multi-tenancy y audit log desde el día 1]])."""
import inspect
import uuid
from pathlib import Path

from app.models.evento_auditoria import EventoAuditoria
from app.models.organizacion import Organizacion
from app.models.usuario import Usuario
from app.services import auditoria


def _crear_org_y_usuario(db_session):
    org = Organizacion(nombre="Bufete Infante")
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


def test_migracion_revoca_update_delete_en_postgres():
    """La inmutabilidad de código no basta: la migración debe revocar
    UPDATE/DELETE al rol de la app sobre `eventos_auditoria` en Postgres.
    SQLite (motor de estos tests) no tiene modelo de permisos, así que esta
    parte solo se puede verificar leyendo la migración, no ejecutándola."""
    versions_dir = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    migraciones = list(versions_dir.glob("*audit_log_inmutable*.py"))
    assert len(migraciones) == 1

    contenido = migraciones[0].read_text(encoding="utf-8")
    assert "REVOKE UPDATE, DELETE ON eventos_auditoria FROM CURRENT_USER" in contenido
