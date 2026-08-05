"""Conexión a base de datos: engine, sesiones y declarative base.

Un solo lugar de verdad para el acceso a datos (Reglas de trabajo del
desarrollador único). El engine se crea de forma perezosa (SQLAlchemy no abre
conexión hasta el primer uso), así que importar este módulo sin una
`DATABASE_URL` real no falla — necesario para que tests y otros módulos
puedan importar `Base` sin depender de una Postgres disponible.
"""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

engine = create_engine(settings.database_url)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    """Dependencia de FastAPI: una sesión por petición, cerrada al terminar."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
