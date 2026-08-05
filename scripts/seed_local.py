"""Puebla la base local con datos sintéticos. Nunca con datos de producción.

Por qué sintéticos y no una copia de Railway
--------------------------------------------
Decidido el 2026-08-05 (bóveda: «Réplica local de Postgres sin datos de
producción»). Un volcado de producción en el portátil es una fuga esperando
turno, y el día que Railway tenga expedientes reales de un bufete el coste de
esa fuga no es recuperable. Los datos sintéticos, además, tienen una ventaja
que la copia no tiene: se eligen para ejercitar los casos que importan, en vez
de reflejar lo que hubiera ese día en producción.

Los casos que estos datos ejercitan a propósito
------------------------------------------------
1. **Dos organizaciones.** Cualquier consulta que se olvide de filtrar por
   `organizacion_id` devuelve filas de más y se nota. Con un solo tenant, un
   fallo de aislamiento es invisible.
2. **El mismo email en las dos organizaciones.** Es exactamente lo que permite
   `uq_usuarios_organizacion_email` (bóveda: «Email único por organización, no
   global»). Si alguien "arregla" esa restricción para hacerla global, este
   seed deja de cargar — que es la forma barata de enterarse.
3. **Un evento de auditoría con `entidad_id` NULL.** El caso del rate-limit de
   login por IP de T4: un evento auditable que no apunta a ninguna fila.

Uso
---
    docker compose up -d db
    alembic upgrade head
    python scripts/seed_local.py

Es idempotente: borra lo que sembró antes (por UUID fijo) y vuelve a sembrar.
"""
import sys
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_contrasena
from app.models.evento_auditoria import EventoAuditoria
from app.models.organizacion import Organizacion
from app.models.usuario import Usuario

# UUIDs derivados de un namespace fijo: los mismos en cada ejecución y en cada
# máquina. Eso permite escribir pruebas manuales y documentación que citen un id
# concreto, y hace el borrado previo exacto en vez de un TRUNCATE a ciegas.
NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")


def id_de(nombre: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, nombre)


CONTRASENA = "desarrollo"  # Solo local. Nunca sale de aquí.


def comprobar_que_no_es_produccion(url: str) -> None:
    """Se niega a sembrar en algo que no sea la base local.

    Este script hace DELETE. Correrlo contra Railway por tener la variable de
    entorno equivocada exportada en la terminal borraría datos de verdad, y es
    un error de un solo carácter de distancia. La suite de pruebas ya tiene una
    guarda equivalente; esta es la misma idea aplicada aquí.
    """
    sospechosos = ("rlwy.net", "railway", "amazonaws", "supabase", "neon.tech")
    if any(marca in url for marca in sospechosos):
        sys.exit(
            "DATABASE_URL apunta a un servidor remoto. Este script borra filas y\n"
            "solo debe correr contra la base local. Abortado sin tocar nada."
        )
    if "localhost" not in url and "127.0.0.1" not in url:
        sys.exit(
            "DATABASE_URL no apunta a localhost. Abortado por precaución: si de\n"
            "verdad quieres sembrar ahí, cambia esta comprobación a conciencia."
        )


def sembrar(db: Session) -> None:
    org_a = Organizacion(id=id_de("org-a"), nombre="Bufete Alfa", slug="bufete-alfa")
    org_b = Organizacion(id=id_de("org-b"), nombre="Bufete Beta", slug="bufete-beta")
    db.add_all([org_a, org_b])
    db.flush()

    # El hash se calcula una sola vez: bcrypt es lento a propósito, y con un
    # hash por usuario este script tardaría segundos en vez de milisegundos.
    # Reutilizarlo es aceptable porque la contraseña es la misma y estos datos
    # no son secretos; en producción cada hash lleva su propio salt.
    contrasena_hash = hash_contrasena(CONTRASENA)

    usuarios = [
        # `ana@ejemplo.test` existe en LAS DOS organizaciones. Ver el docstring.
        Usuario(id=id_de("u-a-ana"), organizacion_id=org_a.id,
                email="ana@ejemplo.test", contrasena_hash=contrasena_hash),
        Usuario(id=id_de("u-b-ana"), organizacion_id=org_b.id,
                email="ana@ejemplo.test", contrasena_hash=contrasena_hash),
        Usuario(id=id_de("u-a-luis"), organizacion_id=org_a.id,
                email="luis@ejemplo.test", contrasena_hash=contrasena_hash),
    ]
    db.add_all(usuarios)
    db.flush()

    db.add_all([
        EventoAuditoria(
            id=id_de("ev-1"), organizacion_id=org_a.id, usuario_id=id_de("u-a-ana"),
            accion="usuario.creado", entidad="usuarios", entidad_id=id_de("u-a-luis"),
            detalle={"origen": "seed"},
        ),
        # Sin `entidad_id` y sin `usuario_id`: el caso del rate-limit por IP.
        EventoAuditoria(
            id=id_de("ev-2"), organizacion_id=org_a.id, usuario_id=None,
            accion="login.rechazado", entidad="rate_limit", entidad_id=None,
            detalle={"ip": "203.0.113.10", "intentos": 6},
        ),
        EventoAuditoria(
            id=id_de("ev-3"), organizacion_id=org_b.id, usuario_id=id_de("u-b-ana"),
            accion="sesion.iniciada", entidad="usuarios", entidad_id=id_de("u-b-ana"),
            detalle=None,
        ),
    ])


def main() -> int:
    comprobar_que_no_es_produccion(settings.database_url)

    engine = create_engine(settings.database_url)
    with Session(engine) as db:
        # Orden inverso a las claves ajenas. `eventos_auditoria` no se puede
        # borrar con el rol de la aplicación —la migración le revoca DELETE— así
        # que esto falla si el REVOKE está activo. Es la señal de que la
        # protección funciona: en ese caso, recrear la base con
        # `docker compose down -v` en vez de intentar borrar filas.
        try:
            db.execute(text("DELETE FROM eventos_auditoria"))
        except Exception:
            db.rollback()
            sys.exit(
                "No se pueden borrar filas de `eventos_auditoria` — es de solo\n"
                "INSERT y el REVOKE está haciendo su trabajo. Para volver a\n"
                "sembrar desde cero:  docker compose down -v && docker compose up -d db\n"
                "                     alembic upgrade head && python scripts/seed_local.py"
            )
        db.execute(text("DELETE FROM usuarios"))
        db.execute(text("DELETE FROM organizaciones"))
        sembrar(db)
        db.commit()

    print(
        "Sembrado: 2 organizaciones, 3 usuarios, 3 eventos de auditoría.\n"
        f"Login de desarrollo: ana@ejemplo.test / {CONTRASENA} (org: bufete-alfa o bufete-beta)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
