"""Escribe `openapi.json` en la raíz del repo (C.6, Bloque C).

Versionado a propósito: es lo que hace visible en el diff de cada PR un
cambio de contrato de `/v1` — el SPA (repo aparte) genera su cliente
TypeScript a partir de este archivo (`npx openapi-typescript openapi.json`),
así que un cambio de contrato sin commit de este archivo tiene que romper el
build (ver `.github/workflows/ci.yml`).

No hace falta Postgres para correrlo: `app.core.db.engine` se crea perezoso
(no conecta hasta el primer uso) y `app.openapi()` solo recorre las rutas ya
registradas — ver `app/core/db.py`.

Uso:
    python scripts/exportar_openapi.py
"""
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.main import app  # noqa: E402


def main() -> int:
    esquema = app.openapi()
    destino = RAIZ / "openapi.json"
    # Con salto de línea final: así un editor que respeta "insertar salto al
    # final del archivo" (casi todos) no deja el archivo con un diff de una
    # sola línea en cada commit que no toca el contrato.
    destino.write_text(json.dumps(esquema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Escrito {destino} ({len(esquema.get('paths', {}))} rutas).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
