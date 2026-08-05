"""Valida el modelo de datos base: organizacion_id NOT NULL y email único."""
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
    assert usuario.creado_en is not None


def test_usuario_sin_organizacion_falla(db_session):
    usuario = Usuario(email="sin.org@example.com", contrasena_hash="hash-de-prueba")
    db_session.add(usuario)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_email_duplicado_falla(db_session):
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
