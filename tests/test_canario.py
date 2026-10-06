"""Canario: pasa con la forma esperada y se pone rojo cuando la Rama cambia."""
from app.jobs.canario import correr, verificar
from tests.test_rama_judicial import ID_PROCESO, RADICADO, _conector, _fixture, _router

BUSQUEDA = "/api/v2/Procesos/Consulta/NumeroRadicacion"
DETALLE = f"/api/v2/Proceso/Detalle/{ID_PROCESO}"
ACTUACIONES = f"/api/v2/Proceso/Actuaciones/{ID_PROCESO}"


def _rutas(**cambios):
    p1 = _fixture("actuaciones_p1.json")
    p1["paginacion"] = {"cantidadPaginas": 1, "pagina": 1}
    busqueda = _fixture("busqueda.json")
    busqueda["procesos"] = busqueda["procesos"][:1]
    rutas = {
        BUSQUEDA: (200, busqueda),
        DETALLE: (200, _fixture("detalle.json")),
        ACTUACIONES: (200, p1),
    }
    rutas.update(cambios)
    return rutas


def _verificar(rutas):
    h = _router(rutas)
    c, _ = _conector(h)
    return verificar(c, RADICADO), h


def test_con_la_forma_esperada_pasa():
    r, h = _verificar(_rutas())
    assert r.ok and r.procesos == 1 and r.actuaciones == 40
    assert len(h.llamadas) == 3  # búsqueda, detalle, una página de actuaciones


def test_cambio_de_forma_en_actuaciones_lo_pone_en_rojo():
    mala = {"actuaciones": [{"otroNombre": 1}], "paginacion": {"cantidadPaginas": 1, "pagina": 1}}
    r, _ = _verificar(_rutas(**{ACTUACIONES: (200, mala)}))
    assert not r.ok and "RespuestaInvalida" in r.motivo


def test_cambio_de_forma_en_la_busqueda_lo_pone_en_rojo():
    r, _ = _verificar(_rutas(**{BUSQUEDA: (200, {"resultados": []})}))
    assert not r.ok and "RespuestaInvalida" in r.motivo


def test_radicado_que_ya_no_existe_se_dice_claro():
    r, _ = _verificar(_rutas(**{BUSQUEDA: (200, {"procesos": []})}))
    assert not r.ok and "ya no existe" in r.motivo


def test_fuente_caida_o_bloqueada_es_rojo():
    r, _ = _verificar(_rutas(**{BUSQUEDA: (503, {})}))
    assert not r.ok and "FuenteNoDisponible" in r.motivo
    r, _ = _verificar(_rutas(**{BUSQUEDA: (429, {})}))
    assert not r.ok and "FuenteRechazo" in r.motivo


def test_sin_actuaciones_en_un_proceso_que_las_tiene_es_rojo():
    vacia = {"actuaciones": [], "paginacion": {"cantidadPaginas": 1, "pagina": 1}}
    r, _ = _verificar(_rutas(**{ACTUACIONES: (200, vacia)}))
    assert not r.ok and "no devolvió actuaciones" in r.motivo


def test_radicado_mal_configurado_es_rojo_sin_salir_a_la_red():
    h = _router({})
    c, _ = _conector(h)
    assert not verificar(c, "123").ok and h.llamadas == []


def test_codigos_de_salida_y_cierre_del_conector():
    c1, _ = _conector(_router(_rutas()))
    cerrado = []
    c1.close = lambda: cerrado.append(True)
    assert correr(crear_fuente=lambda: c1, radicado=RADICADO) == 0 and cerrado

    c2, _ = _conector(_router(_rutas(**{BUSQUEDA: (503, {})})))
    assert correr(crear_fuente=lambda: c2, radicado=RADICADO) == 1


def test_error_inesperado_sale_con_1():
    def mal():
        raise RuntimeError("x")

    assert correr(crear_fuente=mal, radicado=RADICADO) == 1
