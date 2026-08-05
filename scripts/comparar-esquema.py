"""Compara el esquema de Railway con el que producen las migraciones en local.

Por qué este script existe y no uno que copie datos
---------------------------------------------------
La petición original era «un Postgres local copiado de Railway». Al mirarlo de
cerca, copiar los datos no aporta nada y sí arriesga: hoy Railway solo tiene
datos de prueba, y la política acordada (ver la bóveda,
«Réplica local de Postgres sin datos de producción») es que ningún dato de
producción baje nunca a una máquina de desarrollo. Con eso, lo único que
merece la pena traerse de Railway es el **esquema**, y no para instalarlo
—`alembic upgrade head` ya lo genera— sino para **comprobar que coincide**.

Esa comprobación es la que tiene valor real: detecta deriva. Si alguien tocó
producción a mano, o una migración se aplicó a medias, o Railway quedó en una
revisión anterior, aquí se ve. Es el fallo que de otro modo aparece el día del
despliegue.

Cómo lo usa
-----------
    export DATABASE_PUBLIC_URL='postgresql://...@...proxy.rlwy.net:PUERTO/railway'
    python scripts/comparar-esquema.py

Salida 0 = los esquemas coinciden. Salida 1 = hay deriva, y la imprime.

Sobre `pg_dump`: no se usa el del sistema, se usa el del contenedor
`postgres:18` vía `docker run`. Así el cliente siempre empata con la major del
servidor sin que haya que instalar nada en Windows, y no puede darse el caso de
dumpear Railway 18 con un cliente 16 (que falla) ni al revés.

La URL de Railway **nunca** se escribe aquí ni en ningún archivo del repo:
entra por variable de entorno y se pasa al contenedor con `--env`, no en la
línea de comandos, para que no quede en el historial de shell ni en `ps`.
"""
import os
import re
import subprocess
import sys

IMAGEN = "postgres:18"

# Esquema local: se lee desde el contenedor, así que `localhost` no sirve —
# dentro del contenedor de `docker run` eso apunta al propio contenedor.
URL_LOCAL = "postgresql://api_legal_app:api_legal_app@host.docker.internal:5432/api_legal"


def volcar_esquema(url: str, etiqueta: str) -> str:
    """Devuelve el DDL de `url`. Sin datos: --schema-only, siempre."""
    try:
        proceso = subprocess.run(
            [
                "docker", "run", "--rm", "--env", "PGURL",
                # Necesario para que el contenedor alcance el Postgres del host
                # en Linux; en Docker Desktop (Windows/macOS) ya viene resuelto.
                "--add-host", "host.docker.internal:host-gateway",
                IMAGEN,
                "sh", "-c",
                # --no-owner: los owners difieren por diseño (en Railway el rol
                #   es `postgres`, en local `api_legal_app`). No es deriva.
                # Los privilegios SÍ se comparan: el REVOKE que protege el audit
                #   log vive ahí, y saber que en Railway no aplica es justo lo
                #   que queremos que salte a la vista.
                'pg_dump --schema-only --no-owner "$PGURL"',
            ],
            env={**os.environ, "PGURL": url},
            capture_output=True,
            text=True,
            timeout=180,
        )
    except FileNotFoundError:
        sys.exit("No se encontró `docker`. Hace falta Docker para correr este script.")
    except subprocess.TimeoutExpired:
        sys.exit(f"Timeout volcando el esquema de {etiqueta}.")

    if proceso.returncode != 0:
        # stderr puede contener la URL en un mensaje de error de conexión.
        # Se recorta la contraseña antes de enseñarlo.
        error = re.sub(r"://[^@/\s]+@", "://***@", proceso.stderr)
        sys.exit(f"pg_dump falló contra {etiqueta}:\n{error}")

    return proceso.stdout


def normalizar(ddl: str) -> list[str]:
    """Quita el ruido que difiere entre dos dumps del mismo esquema.

    Sin esto el diff es ilegible: cabeceras con la versión exacta del binario,
    `SET` de sesión, líneas en blanco y comentarios de sección. Nada de eso es
    esquema. Lo que queda —CREATE, ALTER, GRANT, REVOKE, COMMENT— sí lo es.
    """
    lineas = []
    for linea in ddl.splitlines():
        linea = linea.rstrip()
        if not linea or linea.startswith("--"):
            continue
        if re.match(r"^(SET|SELECT pg_catalog\.set_config)\b", linea):
            continue
        lineas.append(linea)
    return lineas


def main() -> int:
    url_railway = os.environ.get("DATABASE_PUBLIC_URL")
    if not url_railway:
        sys.exit(
            "Falta DATABASE_PUBLIC_URL.\n"
            "Es la URL pública del Postgres de Railway (la del proxy .rlwy.net;\n"
            "la .railway.internal solo resuelve dentro de su red). Se exporta en\n"
            "la terminal, no se escribe en ningún archivo del repo."
        )

    railway = normalizar(volcar_esquema(url_railway, "Railway"))
    local = normalizar(volcar_esquema(URL_LOCAL, "local"))

    if railway == local:
        print(f"Esquemas idénticos ({len(local)} sentencias). Sin deriva.")
        return 0

    import difflib

    print("DERIVA DETECTADA entre Railway y el esquema local.\n")
    print("\n".join(difflib.unified_diff(railway, local, "railway", "local", lineterm="", n=2)))
    print(
        "\nAntes de 'arreglar' nada: comprobar si la diferencia es esperada.\n"
        "Las conocidas a 2026-08-05 son los privilegios sobre `eventos_auditoria`\n"
        "—en Railway el rol es superusuario y el REVOKE es inerte, riesgo aceptado\n"
        "y planificado para F3. Cualquier otra cosa es deriva de verdad."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
