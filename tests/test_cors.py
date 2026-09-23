"""CORS por lista blanca (C.2, Bloque C).

`test_sin_cors_origenes_configurado_no_hay_cabeceras_cors` prueba el `app`
real: en las pruebas `CORS_ORIGENES` no está puesto, así que
`settings.cors_origenes_lista` es `[]` — el estado seguro por defecto — y
comprueba que ningún origen recibe cabeceras CORS.

El resto monta un `CORSMiddleware` propio con
`app.main.CORS_METODOS`/`CORS_CABECERAS` (los mismos valores que usa el `app`
real, no una copia a mano) y una lista blanca explícita: `settings` es un
singleton leído una sola vez al importar `app.main`, así que no hay forma de
hacer que el `app` real sirva a dos listas blancas distintas dentro de la
misma sesión de pytest.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.main import CORS_CABECERAS, CORS_METODOS

ORIGEN_PERMITIDO = "https://app.ejemplo.com"
ORIGEN_AJENO = "https://otro.example"


def _app_con_lista_blanca(origenes: list[str]) -> FastAPI:
    app_prueba = FastAPI()
    app_prueba.add_middleware(
        CORSMiddleware,
        allow_origins=origenes,
        allow_credentials=True,
        allow_methods=CORS_METODOS,
        allow_headers=CORS_CABECERAS,
    )

    @app_prueba.get("/algo")
    def _algo():
        return {"ok": True}

    return app_prueba


def test_sin_cors_origenes_configurado_no_hay_cabeceras_cors(client):
    """Estado por defecto del `app` real (Reglas de trabajo: default seguro).
    Sin ningún origen en la lista blanca, `CORSMiddleware` no añade
    `access-control-allow-origin` — el navegador bloquea la lectura cruzada."""
    respuesta = client.get("/v1/health", headers={"Origin": ORIGEN_PERMITIDO})

    assert respuesta.status_code == 200
    assert "access-control-allow-origin" not in respuesta.headers


def test_origen_en_la_lista_recibe_las_cabeceras_cors():
    with TestClient(_app_con_lista_blanca([ORIGEN_PERMITIDO])) as cliente:
        respuesta = cliente.get("/algo", headers={"Origin": ORIGEN_PERMITIDO})

    assert respuesta.status_code == 200
    assert respuesta.headers["access-control-allow-origin"] == ORIGEN_PERMITIDO
    assert respuesta.headers["access-control-allow-credentials"] == "true"


def test_origen_ajeno_no_recibe_cabeceras_cors():
    with TestClient(_app_con_lista_blanca([ORIGEN_PERMITIDO])) as cliente:
        respuesta = cliente.get("/algo", headers={"Origin": ORIGEN_AJENO})

    assert respuesta.status_code == 200
    assert "access-control-allow-origin" not in respuesta.headers


def test_preflight_del_origen_permitido_autoriza_metodos_y_cabeceras():
    with TestClient(_app_con_lista_blanca([ORIGEN_PERMITIDO])) as cliente:
        respuesta = cliente.options(
            "/algo",
            headers={
                "Origin": ORIGEN_PERMITIDO,
                "Access-Control-Request-Method": "PATCH",
                "Access-Control-Request-Headers": "authorization,x-csrf-token",
            },
        )

    assert respuesta.status_code == 200
    assert respuesta.headers["access-control-allow-origin"] == ORIGEN_PERMITIDO
    metodos_permitidos = {m.strip() for m in respuesta.headers["access-control-allow-methods"].split(",")}
    assert metodos_permitidos == set(CORS_METODOS)
