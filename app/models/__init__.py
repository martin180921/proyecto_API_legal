"""Importa todos los modelos para que Base.metadata los conozca (Alembic autogenerate, create_all)."""
from app.models.organizacion import Organizacion  # noqa: F401
from app.models.usuario import Usuario  # noqa: F401
from app.models.evento_auditoria import EventoAuditoria  # noqa: F401
from app.models.expediente import Expediente  # noqa: F401
