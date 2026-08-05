"""Fixtures compartidas. Base de datos de pruebas: SQLite en memoria.

`db_session` da una sesión envuelta en una transacción que se revierte al
final de cada test, para que los tests no se contaminen entre sí.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base
import app.models  # noqa: F401 — registra los modelos en Base.metadata


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    try:
        yield session
    finally:
        session.close()
        # Un IntegrityError durante el test ya deja la transacción revertida
        # por dentro; solo cerramos la nuestra si SQLAlchemy no lo hizo ya.
        if transaction.is_active:
            transaction.rollback()
        connection.close()
        engine.dispose()
