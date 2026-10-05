import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from app.connectors.base import (
    ErrorFuente,
    EstadoVisto,
    FuenteNoDisponible,
    FuenteRechazo,
    ProcesoNoEncontrado,
    RespuestaInvalida,
    ResultadoConsulta,
)
from app.connectors.rama_judicial import ZONA, RamaJudicial

FIXTURES = Path(__file__).parent / "fixtures" / "rama_judicial"
RADICADO = "11001400300520210036900"
ID_PROCESO = 88326800


def _fixture(nombre):
    return json.loads((FIXTURES / nombre).read_text(encoding="utf-8"))


class Reloj:
    """Reloj falso: `dormir` lo avanza, así el espaciado se prueba sin esperar."""

    def __init__(self):
        self.t = 0.0
        self.pausas: list[float] = []

    def __call__(self):
        return self.t

    def dormir(self, s):
        self.pausas.append(s)
        self.t += s


def _conector(handler, **kw):
    reloj = Reloj()
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return (
        RamaJudicial(client, reloj=reloj, dormir=reloj.dormir, **kw),
        reloj,
    )


def _router(rutas):
    """handler: ruta (path) -> (status, json) o lista de ellas para llamadas sucesivas."""
    llamadas: list[httpx.Request] = []

    def handler(req: httpx.Request):
        llamadas.append(req)
        r = rutas[req.url.path]
        if isinstance(r, list):
            r = r.pop(0) if len(r) > 1 else r[0]
        status, cuerpo = r
        if isinstance(cuerpo, httpx.Response):
            return cuerpo
        return httpx.Response(status, json=cuerpo)

    handler.llamadas = llamadas
    return handler


# -- resolver ---------------------------------------------------------------


def test_resolver_devuelve_todos_los_procesos_del_radicado():
    h = _router({"/api/v2/Procesos/Consulta/NumeroRadicacion": (200, _fixture("busqueda.json"))})
    c, _ = _conector(h)
    procesos = c.resolver(RADICADO)
    # C.1 del spike: dos idProceso para el mismo radicado; el segundo > int32.
    assert [p.id_externo for p in procesos] == [88326800, 3290051731]
    assert procesos[1].id_externo > 2**31 - 1
    assert procesos[0].despacho == "JUZGADO 005 CIVIL MUNICIPAL DE BOGOTÁ"
    assert procesos[0].es_privado is False
    assert procesos[0].fecha_ultima_actuacion.tzinfo == ZONA
    assert procesos[0].crudo["idProceso"] == 88326800
    q = h.llamadas[0].url.params
    assert q["numero"] == RADICADO and q["SoloActivos"] == "false"


def test_resolver_lista_vacia_es_no_encontrado_no_error():
    h = _router({"/api/v2/Procesos/Consulta/NumeroRadicacion": (200, {"procesos": []})})
    c, _ = _conector(h)
    assert c.resolver(RADICADO) == []


@pytest.mark.parametrize("malo", ["", "123", "ABC00300520210036900", RADICADO + "0", "2004-0123"])
def test_resolver_rechaza_lo_que_no_es_radicado_de_23_digitos(malo):
    h = _router({})
    c, _ = _conector(h)
    with pytest.raises(ValueError):
        c.resolver(malo)
    assert h.llamadas == []  # ni siquiera sale a la red


def test_resolver_pagina_hasta_cantidad_paginas():
    base = _fixture("busqueda.json")
    p1 = {**base, "procesos": base["procesos"][:1], "paginacion": {"cantidadPaginas": 2, "pagina": 1}}
    p2 = {**base, "procesos": base["procesos"][1:], "paginacion": {"cantidadPaginas": 2, "pagina": 2}}
    h = _router({"/api/v2/Procesos/Consulta/NumeroRadicacion": [(200, p1), (200, p2)]})
    c, _ = _conector(h)
    assert len(c.resolver(RADICADO)) == 2
    assert [r.url.params["pagina"] for r in h.llamadas] == ["1", "2"]


# -- consultar --------------------------------------------------------------


def _rutas_consulta(actuaciones):
    return {
        f"/api/v2/Proceso/Detalle/{ID_PROCESO}": (200, _fixture("detalle.json")),
        f"/api/v2/Proceso/Actuaciones/{ID_PROCESO}": actuaciones,
    }


def test_primera_consulta_lee_la_pagina_y_normaliza():
    p1 = _fixture("actuaciones_p1.json")
    p1["paginacion"] = {"cantidadPaginas": 1, "pagina": 1}
    c, _ = _conector(_router(_rutas_consulta((200, p1))))
    r = c.consultar(ID_PROCESO, None)
    assert r.resultado is ResultadoConsulta.CON_ACTUACIONES
    assert len(r.actuaciones_nuevas) == 40
    primera = r.actuaciones_nuevas[0]
    assert primera.id_externo == 2888947820 and primera.consecutivo == 57
    # C.3 del spike: fecha_inicial/final también fuera de «Fijacion estado».
    assert primera.fecha_inicial == datetime(2026, 9, 2, tzinfo=ZONA)
    assert primera.fecha_final == datetime(2026, 10, 14, tzinfo=ZONA)
    assert primera.crudo["idRegActuacion"] == 2888947820
    assert r.ultima_actualizacion == datetime(2026, 10, 5, 14, 59, 23, 770000, tzinfo=ZONA)


def test_primera_consulta_pagina_entero():
    p1 = _fixture("actuaciones_p1.json")  # trae cantidadPaginas=2
    p2 = {"actuaciones": [{**p1["actuaciones"][0], "idRegActuacion": 5, "consActuacion": 1}],
          "paginacion": {"cantidadPaginas": 2, "pagina": 2}}
    h = _router(_rutas_consulta([(200, p1), (200, p2)]))
    c, _ = _conector(h)
    r = c.consultar(ID_PROCESO, None)
    assert len(r.actuaciones_nuevas) == 41
    assert r.actuaciones_nuevas[-1].id_externo == 5


def test_para_en_el_primer_id_ya_visto_y_no_pide_mas_paginas():
    p1 = _fixture("actuaciones_p1.json")
    ids = [a["idRegActuacion"] for a in p1["actuaciones"]]
    visto = EstadoVisto(datetime(2026, 9, 1, tzinfo=ZONA), frozenset(ids[2:]))
    h = _router(_rutas_consulta((200, p1)))
    c, _ = _conector(h)
    r = c.consultar(ID_PROCESO, visto)
    assert [a.id_externo for a in r.actuaciones_nuevas] == ids[:2]
    assert sum("Actuaciones" in x.url.path for x in h.llamadas) == 1


def test_sin_cambios_no_pide_actuaciones():
    detalle = _fixture("detalle.json")
    ultima = datetime(2026, 10, 5, 14, 59, 23, 770000, tzinfo=ZONA)
    # El mismo instante en UTC, como lo devolvería Postgres: debe igualar.
    visto = EstadoVisto(ultima.astimezone(timezone.utc), frozenset({1}))
    h = _router({f"/api/v2/Proceso/Detalle/{ID_PROCESO}": (200, detalle)})
    c, _ = _conector(h)
    r = c.consultar(ID_PROCESO, visto)
    assert r.resultado is ResultadoConsulta.SIN_CAMBIOS
    assert len(h.llamadas) == 1


def test_cambio_sin_actuaciones_nuevas():
    p1 = _fixture("actuaciones_p1.json")
    visto = EstadoVisto(
        datetime(2026, 1, 1, tzinfo=ZONA),
        frozenset(a["idRegActuacion"] for a in p1["actuaciones"]),
    )
    c, _ = _conector(_router(_rutas_consulta((200, p1))))
    r = c.consultar(ID_PROCESO, visto)
    assert r.resultado is ResultadoConsulta.CAMBIO_SIN_ACTUACIONES
    assert r.actuaciones_nuevas == ()


def test_detalle_404_es_proceso_no_encontrado():
    h = _router({f"/api/v2/Proceso/Detalle/{ID_PROCESO}": (404, {"StatusCode": 404})})
    c, _ = _conector(h)
    with pytest.raises(ProcesoNoEncontrado):
        c.consultar(ID_PROCESO, None)


# -- formas inválidas: jamás «sin cambios» ----------------------------------


@pytest.mark.parametrize(
    "cuerpo",
    [
        {},  # sin ultimaActualizacion
        {"ultimaActualizacion": "no-es-fecha"},
        [],
    ],
)
def test_detalle_con_otra_forma_es_respuesta_invalida(cuerpo):
    h = _router({f"/api/v2/Proceso/Detalle/{ID_PROCESO}": (200, cuerpo)})
    c, _ = _conector(h)
    with pytest.raises(RespuestaInvalida):
        c.consultar(ID_PROCESO, None)


def test_actuacion_sin_id_es_respuesta_invalida():
    p1 = {"actuaciones": [{"consActuacion": 1, "fechaActuacion": "2026-01-01T00:00:00", "actuacion": "x"}]}
    c, _ = _conector(_router(_rutas_consulta((200, p1))))
    with pytest.raises(RespuestaInvalida):
        c.consultar(ID_PROCESO, None)


def test_cuerpo_que_no_es_json_es_respuesta_invalida():
    h = _router({"/api/v2/Procesos/Consulta/NumeroRadicacion": (200, httpx.Response(200, text="<html>"))})
    c, _ = _conector(h)
    with pytest.raises(RespuestaInvalida):
        c.resolver(RADICADO)


def test_400_es_respuesta_invalida_y_no_se_reintenta():
    h = _router({"/api/v2/Procesos/Consulta/NumeroRadicacion": (400, {})})
    c, _ = _conector(h)
    with pytest.raises(RespuestaInvalida):
        c.resolver(RADICADO)
    assert len(h.llamadas) == 1


def test_cantidad_paginas_absurda_tiene_tope():
    p = {"actuaciones": [], "paginacion": {"cantidadPaginas": 10_000, "pagina": 1}}
    h = _router(_rutas_consulta((200, p)))
    c, _ = _conector(h, max_paginas=3)
    with pytest.raises(RespuestaInvalida):
        c.consultar(ID_PROCESO, None)
    assert len(h.llamadas) <= 4


# -- disciplina de salida ---------------------------------------------------


def test_espacia_las_peticiones_a_un_segundo():
    p1 = _fixture("actuaciones_p1.json")
    p1["paginacion"] = {"cantidadPaginas": 1, "pagina": 1}
    c, reloj = _conector(_router(_rutas_consulta((200, p1))))
    c.consultar(ID_PROCESO, None)  # detalle + actuaciones = 2 peticiones
    assert reloj.pausas == [1.0]


def test_reintenta_5xx_y_se_recupera():
    h = _router(
        {"/api/v2/Procesos/Consulta/NumeroRadicacion": [(503, {}), (200, {"procesos": []})]}
    )
    c, reloj = _conector(h)
    assert c.resolver(RADICADO) == []
    assert len(h.llamadas) == 2
    assert not c.circuito_abierto


def test_5xx_persistente_es_fuente_no_disponible_tras_los_reintentos():
    h = _router({"/api/v2/Procesos/Consulta/NumeroRadicacion": (500, {})})
    c, _ = _conector(h, reintentos=2)
    with pytest.raises(FuenteNoDisponible):
        c.resolver(RADICADO)
    assert len(h.llamadas) == 3


def test_fallo_de_transporte_se_reintenta_y_luego_falla():
    def handler(req):
        raise httpx.ConnectTimeout("lento", request=req)

    c, _ = _conector(handler, reintentos=1)
    with pytest.raises(FuenteNoDisponible):
        c.resolver(RADICADO)


@pytest.mark.parametrize("status", [403, 429])
def test_rechazo_abre_el_circuito_y_no_se_reintenta(status):
    h = _router({"/api/v2/Procesos/Consulta/NumeroRadicacion": (status, {})})
    c, _ = _conector(h)
    with pytest.raises(FuenteRechazo):
        c.resolver(RADICADO)
    assert c.circuito_abierto and len(h.llamadas) == 1
    # Con el circuito abierto, nada más sale a la red en toda la corrida.
    with pytest.raises(FuenteNoDisponible):
        c.resolver(RADICADO)
    with pytest.raises(FuenteNoDisponible):
        c.consultar(ID_PROCESO, None)
    assert len(h.llamadas) == 1


def test_fallos_seguidos_abren_el_circuito():
    h = _router({"/api/v2/Procesos/Consulta/NumeroRadicacion": (500, {})})
    c, _ = _conector(h, reintentos=0, max_fallos_seguidos=3)
    for _ in range(3):
        with pytest.raises(FuenteNoDisponible):
            c.resolver(RADICADO)
    assert c.circuito_abierto
    with pytest.raises(FuenteNoDisponible, match="circuito abierto"):
        c.resolver(RADICADO)
    assert len(h.llamadas) == 3


def test_un_exito_reinicia_la_cuenta_de_fallos():
    h = _router(
        {"/api/v2/Procesos/Consulta/NumeroRadicacion": [
            (500, {}), (500, {}), (200, {"procesos": []}), (500, {}), (500, {}), (200, {"procesos": []})
        ]}
    )
    c, _ = _conector(h, reintentos=0, max_fallos_seguidos=3)
    for esperado in (FuenteNoDisponible, FuenteNoDisponible, None, FuenteNoDisponible, FuenteNoDisponible, None):
        if esperado:
            with pytest.raises(esperado):
                c.resolver(RADICADO)
        else:
            assert c.resolver(RADICADO) == []
    assert not c.circuito_abierto


def test_presupuesto_de_tiempo_por_operacion():
    p1 = {"actuaciones": [], "paginacion": {"cantidadPaginas": 5, "pagina": 1}}
    h = _router(_rutas_consulta((200, p1)))
    c, _ = _conector(h, presupuesto=1.5)  # el espaciado de 1 s agota 1,5 s en la 3.ª petición
    with pytest.raises(FuenteNoDisponible, match="presupuesto"):
        c.consultar(ID_PROCESO, None)


def test_el_user_agent_es_identificable():
    h = _router({"/api/v2/Procesos/Consulta/NumeroRadicacion": (200, {"procesos": []})})
    # Cliente propio de la clase (no inyectado) con transporte falso.
    c = RamaJudicial(reloj=Reloj(), dormir=lambda s: None)
    assert c._client.headers["user-agent"].startswith("api-legal-revisor")
    c.close()


def test_todo_error_de_la_fuente_es_error_fuente():
    h = _router({"/api/v2/Procesos/Consulta/NumeroRadicacion": (500, {})})
    c, _ = _conector(h, reintentos=0)
    with pytest.raises(ErrorFuente):
        c.resolver(RADICADO)
