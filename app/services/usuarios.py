"""Lecturas de `Usuario` para el selector de responsable del SPA (C.5, Bloque
C). Sin mutaciones aquí — el alta de usuario sigue siendo
`scripts/crear_organizacion.py`, fuera de esta API."""
import uuid

from sqlalchemy.orm import Session

from app.models.usuario import Usuario


def listar(db: Session, organizacion_id: uuid.UUID) -> list[Usuario]:
    return (
        db.query(Usuario)
        .filter_by(organizacion_id=organizacion_id)
        .order_by(Usuario.nombre, Usuario.id)
        .all()
    )
