"""Escritura del audit log. Única vía para crear un `EventoAuditoria`.

A propósito, este módulo no expone `actualizar` ni `borrar`: el audit log es
solo INSERT ([[Multi-tenancy y audit log desde el día 1]]). Se llama desde
todo servicio que mute datos (regla 9 del documento de Juan Diego). No hace
`commit`: queda en la misma transacción que la mutación que audita, para que
ambas se confirmen o se reviertan juntas.

`entidad_id` es opcional: hay eventos auditables que no apuntan a ninguna fila
(rate-limit de login por IP, T4). `entidad` no lo es — un evento sin tipo no
sirve para nada.

Cada evento generado dentro de una petición HTTP lleva además `request_id` en
`detalle` (A.3.3, Bloque A2, 2026-08-16): es lo que une esta fila con la línea
del log estructurado que dejó `app/main.py::log_requests` para la misma
petición. Fuera de una petición (scripts, importador) no hay `request_id` que
añadir y `detalle` queda tal cual lo pasó el llamador.
"""
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.contexto import id_peticion_actual
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
    request_id = id_peticion_actual.get()
    if request_id is not None:
        detalle = {**(detalle or {}), "request_id": request_id}

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
