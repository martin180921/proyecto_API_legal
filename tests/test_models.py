"""Valida el modelo de datos base: organizacion_id NOT NULL, integridad
referencial y unicidad del email **por organización**
([[Email único por organización, no global]])."""
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.organizacion import Organizacion
from app.models.usuario import Usuario


def test_crear_organizacion_y_usuario(db_session):
    org = Organizacion(nombre="Bufete Infante")
    db_session.add(org)
    db_session.flush()

    usuario = Usuario(
        organizacion_id=org.id,
        email="juan.diego@example.com",
        contrasena_hash="hash-de-prueba",
    )
    db_session.add(usuario)
    db_session.flush()

    assert usuario.id is not None
    assert usuario.organizacion_id == org.id
    # `creado_en` lo pone la base de datos (server_default), no Python: el
    # valor no existe hasta que la fila está escrita y SQLAlchemy lo relee.
    assert usuario.creado_en is not None


def test_usuario_sin_organizacion_falla(db_session):
    usuario = Usuario(email="sin.org@example.com", contrasena_hash="hash-de-prueba")
    db_session.add(usuario)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_organizacion_inexistente_falla(db_session):
    """Integridad referencial de verdad. Sin `PRAGMA foreign_keys=ON` en el
    conftest, SQLite acepta este huérfano en silencio y el fallo solo
    aparecería en Postgres."""
    usuario = Usuario(
        organizacion_id=uuid.uuid4(),  # no existe ninguna organización con este id
        email="huerfano@example.com",
        contrasena_hash="hash-de-prueba",
    )
    db_session.add(usuario)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_email_duplicado_en_la_misma_organizacion_falla(db_session):
    org = Organizacion(nombre="Bufete Infante")
    db_session.add(org)
    db_session.flush()

    db_session.add(
        Usuario(organizacion_id=org.id, email="repetido@example.com", contrasena_hash="a")
    )
    db_session.flush()

    db_session.add(
        Usuario(organizacion_id=org.id, email="repetido@example.com", contrasena_hash="b")
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_mismo_email_en_dos_organizaciones_es_valido(db_session):
    """La misma persona puede ser usuaria de dos firmas. Es el corolario de
    que la unicidad sea por organización y no global, y condiciona el login
    de T4: el email por sí solo no identifica a un usuario."""
    una = Organizacion(nombre="Bufete Infante")
    otra = Organizacion(nombre="Bufete Aliado")
    db_session.add_all([una, otra])
    db_session.flush()

    db_session.add_all(
        [
            Usuario(organizacion_id=una.id, email="compartido@example.com", contrasena_hash="a"),
            Usuario(organizacion_id=otra.id, email="compartido@example.com", contrasena_hash="b"),
        ]
    )
    db_session.flush()

    assert db_session.query(Usuario).filter_by(email="compartido@example.com").count() == 2
