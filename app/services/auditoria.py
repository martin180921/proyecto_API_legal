"""Escritura del audit log. Única vía para crear un `EventoAuditoria`.

A propósito, este módulo no expone `actualizar` ni `borrar`: el audit log es
solo INSERT ([[Multi-tenancy y audit log desde el día 1]]). Se llama desde
todo servicio que mute datos (regla 9 del documento de Juan Diego). No hace
`commit`: queda en la misma transacción que la mutación que audita, para que
ambas se confirmen o se reviertan juntas.

`entidad_id` es opcional: hay eventos auditables que no apuntan a ninguna fila
(rate-limit de login por IP, T4). `entidad` no lo es — un evento sin tipo no
sirve para nada.
"""
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.evento_auditoria import EventoAuditoria


def registrar(
    db: Session,
    organizacion_id: uuid.UUID,
    accion: str,
    entidad: str,
    entidad_id: uuid.UUID | None = None,
    usuario_id: uuid.UUID | None = None,
    detalle: dict[str, Any] | None = None,
) -> EventoAuditoria:
    evento = EventoAuditoria(
        organizacion_id=organizacion_id,
        usuario_id=usuario_id,
        accion=accion,
        entidad=entidad,
        entidad_id=entidad_id,
        detalle=detalle,
    )
    db.add(evento)
    db.flush()
    return evento
