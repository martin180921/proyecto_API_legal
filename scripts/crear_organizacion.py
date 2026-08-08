"""Alta manual de una organización y su primer usuario.

Por qué existe
--------------
`POST /v1/auth/registro` está **cerrado por defecto** (`REGISTRO_ABIERTO=false`,
ver `app/core/config.py`): F0 no necesita autoservicio, el piloto es un
abogado, y un endpoint público que ejecuta bcrypt sin límite es a la vez una
vía para llenar la base de organizaciones y una forma barata de tumbar el
único proceso de uvicorn que arranca `railway.json`.

Cerrarlo deja un hueco: hay que poder dar de alta a alguien. Esto es ese hueco,
por línea de comandos y con **slug explícito** — a diferencia del endpoint, que
lo genera del nombre, aquí el slug es lo que el usuario va a teclear en cada
login, así que se elige a conciencia y no se deriva.

Uso
---
    python scripts/crear_organizacion.py \
        --nombre "Bufete Infante" --slug bufete-infante \
        --email juan.diego@example.com

La contraseña se pide por consola (no se ve al teclearla) para que no quede en
el historial del shell. `--contrasena` existe para automatizar, con esa pega.

Contra qué base de datos corre: la de `DATABASE_URL`. A diferencia de
`scripts/seed_local.py`, este script **no** se limita a localhost — dar de alta
en producción es justamente para lo que sirve. No borra nada: si el slug o el
email ya existen, se para sin escribir.
"""
import argparse
import getpass
import re
import sys
from pathlib import Path

# `python scripts/crear_organizacion.py` pone `scripts/` en sys.path, no la
# raíz del repositorio, así que sin esto `import app` falla con
# ModuleNotFoundError — o sea, el comando que documenta el README no arranca.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.security import hash_contrasena  # noqa: E402
from app.models.organizacion import Organizacion  # noqa: E402
from app.models.usuario import Usuario  # noqa: E402
from app.services import auditoria  # noqa: E402

# Mismo formato que produce `_slugify` en `app/api/v1/auth.py`: minúsculas,
# números y guiones simples. Se valida aquí porque un slug con mayúsculas o
# espacios es imposible de teclear bien en el login y nadie lo descubriría
# hasta el primer intento fallido del abogado.
FORMATO_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# Los mismos límites que `RegistroRequest` en `app/schemas/auth.py`: el mínimo
# es política, el máximo es bcrypt, que trunca en 72 bytes.
LONGITUD_MINIMA_CONTRASENA = 8
LONGITUD_MAXIMA_CONTRASENA = 72


def pedir_contrasena() -> str:
    contrasena = getpass.getpass("Contraseña del primer usuario: ")
    if contrasena != getpass.getpass("Repite la contraseña: "):
        sys.exit("Las contraseñas no coinciden. No se ha creado nada.")
    return contrasena


def validar(slug: str, contrasena: str) -> None:
    if not FORMATO_SLUG.match(slug):
        sys.exit(
            f"El slug «{slug}» no vale: solo minúsculas, números y guiones simples "
            "(por ejemplo `bufete-infante`). Es lo que se teclea en cada login."
        )
    if not LONGITUD_MINIMA_CONTRASENA <= len(contrasena.encode("utf-8")) <= LONGITUD_MAXIMA_CONTRASENA:
        sys.exit(
            f"La contraseña debe medir entre {LONGITUD_MINIMA_CONTRASENA} y "
            f"{LONGITUD_MAXIMA_CONTRASENA} bytes (bcrypt trunca a partir de ahí)."
        )


def crear(db: Session, nombre: str, slug: str, email: str, contrasena: str) -> tuple[Organizacion, Usuario]:
    if db.query(Organizacion).filter_by(slug=slug).one_or_none() is not None:
        sys.exit(f"Ya existe una organización con el slug «{slug}». No se ha creado nada.")

    organizacion = Organizacion(nombre=nombre, slug=slug)
    db.add(organizacion)
    db.flush()

    usuario = Usuario(
        organizacion_id=organizacion.id,
        email=email,
        contrasena_hash=hash_contrasena(contrasena),
    )
    db.add(usuario)
    db.flush()

    # Mismos eventos que deja `POST /v1/auth/registro`: que un alta se haya
    # hecho por consola no la exime del audit log (regla 9). `usuario_id` es el
    # del usuario creado — no hay sesión de nadie más a quien atribuirla.
    auditoria.registrar(
        db,
        organizacion_id=organizacion.id,
        accion="crear",
        entidad="organizacion",
        entidad_id=organizacion.id,
        detalle={"origen": "scripts/crear_organizacion.py"},
    )
    auditoria.registrar(
        db,
        organizacion_id=organizacion.id,
        accion="crear",
        entidad="usuario",
        entidad_id=usuario.id,
        usuario_id=usuario.id,
        detalle={"origen": "scripts/crear_organizacion.py"},
    )
    return organizacion, usuario


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--nombre", required=True, help='Nombre de la firma, p. ej. "Bufete Infante"')
    parser.add_argument("--slug", required=True, help="Identificador del login, p. ej. bufete-infante")
    parser.add_argument("--email", required=True, help="Email del primer usuario")
    parser.add_argument(
        "--contrasena",
        help="Si se omite, se pide por consola (recomendado: no queda en el historial del shell)",
    )
    args = parser.parse_args()

    contrasena = args.contrasena or pedir_contrasena()
    validar(args.slug, contrasena)

    engine = create_engine(settings.database_url)
    with Session(engine) as db:
        organizacion, usuario = crear(db, args.nombre, args.slug, args.email, contrasena)
        db.commit()

        # La contraseña no se imprime nunca, ni siquiera aquí: esta salida
        # acaba en la terminal y muchas veces en un log de despliegue.
        print(
            f"Organización creada: {organizacion.nombre} (slug: {organizacion.slug})\n"
            f"  id       {organizacion.id}\n"
            f"Primer usuario: {usuario.email}\n"
            f"  id       {usuario.id}\n\n"
            f"El login usa slug + email + contraseña: «{organizacion.slug}» / «{usuario.email}»."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
