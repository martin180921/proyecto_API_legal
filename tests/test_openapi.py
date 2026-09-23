"""`openapi.json` versionado (C.6, Bloque C): red de seguridad local para el
mismo chequeo que hace CI (`git diff --exit-code openapi.json`) — si esta
prueba falla, correr `python scripts/exportar_openapi.py` y commitear el
resultado."""
import json
from pathlib import Path

from app.main import app

RAIZ = Path(__file__).resolve().parent.parent


def test_openapi_json_versionado_coincide_con_el_esquema_actual():
    archivo = RAIZ / "openapi.json"
    assert archivo.exists(), "Falta openapi.json — correr scripts/exportar_openapi.py"

    versionado = json.loads(archivo.read_text(encoding="utf-8"))
    actual = app.openapi()

    assert versionado == actual, (
        "openapi.json está desactualizado respecto al código — "
        "correr `python scripts/exportar_openapi.py` y commitear el resultado."
    )


def test_toda_ruta_de_v1_tiene_operation_id_legible():
    """C.6: `operation_id` es de dónde sale el nombre del método en el
    cliente TypeScript generado — sin uno explícito, FastAPI genera algo como
    `listar_expedientes_v1_expedientes_get`, que no es lo que pide el plan."""
    for ruta in app.routes:
        if not getattr(ruta, "path", "").startswith("/v1"):
            continue
        assert ruta.operation_id is not None, ruta.path
        assert "_get" not in ruta.operation_id
        assert "_post" not in ruta.operation_id
