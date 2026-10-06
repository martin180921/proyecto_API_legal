"""Revisor (Etapa Procesamiento). La fuente es un doble en memoria: el conector
real ya tiene sus propias pruebas con fixtures. Aquí se prueba lo que el
revisor decide: estados de `Revision`, qué persiste, cuándo vuelve a `resolver`,
el filtro de consultables, el circuito abierto y el lock."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.connectors.base import (
    ActuacionNormalizada,
    ConsultaProceso,
    FuenteConsulta,
    FuenteNoDisponible,
    ProcesoEncontrado,
    ResultadoConsulta,
)
from app.models.actuacion import Actuacion
from app.models.expediente import Expediente, Seguimiento, TipoIdentificador, TipoProceso
from app.models.organizacion import Organizacion
from app.models.proceso_fuente import EstadoProcesoFuente, FuenteProceso, ProcesoFuente
from app.models.revision import Revision, ResultadoRevision
from app.services import revisor
from app.services.revisor import CorridaEnCurso, ejecutar_corrida, es_envio_a_otro_despacho

RADICADO = "11001400300520210036900"
AHORA = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
ZONA = timezone(timedelta(hours=-5))


def _act(id_externo, consecutivo=1, tipo="Recepción memorial", anotacion=None, fecha=None):
    return ActuacionNormalizada(
        id_externo=id_externo,
        consecutivo=consecutivo,
        fecha_actuacion=fecha or datetime(2026, 10, 1, tzinfo=ZONA),
        tipo=tipo,
        anotacion=anotacion,
        fecha_inicial=None,
        fecha_final=None,
        fecha_registro=None,
        con_documentos=False,
        crudo={"idRegActuacion": id_externo},
    )


def _encontrado(id_externo):
    return ProcesoEncontrado(
        id_externo=id_externo,
        id_conexion=1,
        despacho="Juzgado 5",
        departamento="Bogotá",
        fecha_ultima_actuacion=None,
        es_privado=False,
        crudo={"idProceso": id_externo},
    )


def _con(actuaciones, ultima=datetime(2026, 10, 2, tzinfo=ZONA)):
    return ConsultaProceso(ResultadoConsulta.CON_ACTUACIONES, ultima, tuple(actuaciones))


class FuenteFalsa(FuenteConsulta):
    fuente = FuenteProceso.RAMA_JUDICIAL

    def __init__(self):
        self.encontrados: dict[str, list[ProcesoEncontrado]] = {}
        self.respuestas: dict[int, object] = {}  # ConsultaProceso o Exception
        self.llamadas_resolver: list[str] = []
        self.llamadas_consultar: list[tuple] = []
        self.abierto = False

    @property
    def circuito_abierto(self):
        return self.abierto

    def resolver(self, identificador):
        self.llamadas_resolver.append(identificador)
        r = self.encontrados.get(identificador, [])
        if isinstance(r, Exception):
            raise r
        return r

    def consultar(self, id_externo, desde):
        self.llamadas_consultar.append((id_externo, desde))
        r = self.respuestas[id_externo]
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture()
def org(db_session):
    o = Organizacion(nombre="Bufete", slug=f"b-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    db_session.commit()  # el revisor hace rollback de sus lecturas
    return o.id


def _expediente(db, org_id, identificador=RADICADO, **kw):
    datos = dict(
        organizacion_id=org_id,
        identificador=identificador,
        tipo_identificador=TipoIdentificador.RADICADO_UNIFICADO,
        seguimiento=Seguimiento.AUTOMATICO,
        tipo_proceso=TipoProceso.CIVIL,
    )
    datos.update(kw)
    e = Expediente(**datos)
    db.add(e)
    db.commit()
    return e.id


def _correr(db, engine, fuente, **kw):
    return ejecutar_corrida(lambda: db, fuente, engine=engine, ahora=AHORA, **kw)


def _revisiones(db, exp_id):
    return list(
        db.execute(
            select(Revision).where(Revision.expediente_id == exp_id).order_by(Revision.creado_en)
        ).scalars()
    )


def _procesos(db, exp_id):
    return list(
        db.execute(select(ProcesoFuente).where(ProcesoFuente.expediente_id == exp_id)).scalars()
    )


# -- el caso feliz y sus variantes ----------------------------------------------


def test_primera_vez_carga_la_linea_base_y_no_es_novedad(db_session, engine, org):
    exp = _expediente(db_session, org)
    f = FuenteFalsa()
    f.encontrados[RADICADO] = [_encontrado(100)]
    f.respuestas[100] = _con([_act(2, 2), _act(1, 1)])

    resumen = _correr(db_session, engine, f)

    (rev,) = _revisiones(db_session, exp)
    assert rev.resultado == ResultadoRevision.SIN_NOVEDAD
    assert "línea base: 2" in rev.detalle
    assert rev.corrida_id == resumen.corrida_id
    (p,) = _procesos(db_session, exp)
    assert p.ultima_actualizacion_fuente is not None and p.fecha_ultima_consulta == AHORA
    actuaciones = db_session.execute(select(Actuacion)).scalars().all()
    assert {a.id_externo for a in actuaciones} == {1, 2}
    assert {a.revision_id for a in actuaciones} == {rev.id}
    # Proceso recién dado de alta: `desde=None`, se pagina entero.
    assert f.llamadas_consultar[0] == (100, None)


def test_segunda_corrida_persiste_solo_lo_nuevo_y_manda_el_estado_visto(
    db_session, engine, org
):
    exp = _expediente(db_session, org)
    f = FuenteFalsa()
    f.encontrados[RADICADO] = [_encontrado(100)]
    f.respuestas[100] = _con([_act(2, 2), _act(1, 1)])
    _correr(db_session, engine, f)

    f.respuestas[100] = _con(
        [_act(3, 3)], ultima=datetime(2026, 10, 5, tzinfo=ZONA)
    )
    _correr(db_session, engine, f)

    id_externo, desde = f.llamadas_consultar[-1]
    assert id_externo == 100
    assert desde.ids_actuaciones_vistas == frozenset({1, 2})
    assert desde.ultima_actualizacion == datetime(2026, 10, 2, tzinfo=ZONA)
    assert [r.resultado for r in _revisiones(db_session, exp)] == [
        ResultadoRevision.SIN_NOVEDAD,
        ResultadoRevision.CON_NOVEDAD,
    ]
    assert db_session.scalar(select(Actuacion.id_externo).where(Actuacion.id_externo == 3))
    assert len(db_session.execute(select(Actuacion)).scalars().all()) == 3
    assert f.llamadas_resolver == [RADICADO]  # solo la primera vez


def test_sin_cambios_es_sin_novedad_y_no_persiste_actuaciones(db_session, engine, org):
    exp = _expediente(db_session, org)
    f = FuenteFalsa()
    f.encontrados[RADICADO] = [_encontrado(100)]
    f.respuestas[100] = _con([_act(1)])
    _correr(db_session, engine, f)
    f.respuestas[100] = ConsultaProceso(
        ResultadoConsulta.SIN_CAMBIOS, datetime(2026, 10, 2, tzinfo=ZONA)
    )
    _correr(db_session, engine, f)

    ultima = _revisiones(db_session, exp)[-1]
    assert ultima.resultado == ResultadoRevision.SIN_NOVEDAD
    assert ultima.detalle is None
    assert len(db_session.execute(select(Actuacion)).scalars().all()) == 1


def test_error_de_fuente_es_no_verificado_nunca_sin_novedad(db_session, engine, org):
    exp = _expediente(db_session, org)
    f = FuenteFalsa()
    f.encontrados[RADICADO] = [_encontrado(100)]
    f.respuestas[100] = _con([_act(1)])
    _correr(db_session, engine, f)
    antes = _procesos(db_session, exp)[0].ultima_actualizacion_fuente

    f.respuestas[100] = FuenteNoDisponible("HTTP 503")
    _correr(db_session, engine, f)

    ultima = _revisiones(db_session, exp)[-1]
    assert ultima.resultado == ResultadoRevision.NO_VERIFICADO
    assert "HTTP 503" in ultima.detalle
    # Lo que no se pudo verificar no avanza el estado visto.
    assert _procesos(db_session, exp)[0].ultima_actualizacion_fuente == antes


def test_resolver_vacio_es_no_encontrado(db_session, engine, org):
    exp = _expediente(db_session, org)
    f = FuenteFalsa()  # `resolver` devuelve []
    _correr(db_session, engine, f)

    (rev,) = _revisiones(db_session, exp)
    assert rev.resultado == ResultadoRevision.NO_ENCONTRADO
    assert _procesos(db_session, exp) == []
    # Y se vuelve a intentar mañana: el radicado puede indexarse después.
    _correr(db_session, engine, f)
    assert len(f.llamadas_resolver) == 2


def test_resolver_que_falla_es_no_verificado_no_no_encontrado(db_session, engine, org):
    exp = _expediente(db_session, org)
    f = FuenteFalsa()
    f.encontrados[RADICADO] = FuenteNoDisponible("timeout")
    _correr(db_session, engine, f)
    assert _revisiones(db_session, exp)[0].resultado == ResultadoRevision.NO_VERIFICADO


def test_novedad_gana_a_un_fallo_parcial_y_el_fallo_queda_en_el_detalle(
    db_session, engine, org
):
    exp = _expediente(db_session, org)
    f = FuenteFalsa()
    f.encontrados[RADICADO] = [_encontrado(100), _encontrado(200)]
    f.respuestas[100] = _con([_act(1)])
    f.respuestas[200] = _con([_act(10)])
    _correr(db_session, engine, f)

    f.respuestas[100] = _con([_act(2, 2)])
    f.respuestas[200] = FuenteNoDisponible("HTTP 500")
    _correr(db_session, engine, f)

    ultima = _revisiones(db_session, exp)[-1]
    assert ultima.resultado == ResultadoRevision.CON_NOVEDAD
    assert "200" in ultima.detalle and "HTTP 500" in ultima.detalle


# -- filtro, circuito, lock ------------------------------------------------------


def test_solo_se_revisan_automaticos_con_radicado_unificado(db_session, engine, org):
    bueno = _expediente(db_session, org)
    manual = _expediente(
        db_session, org, "22222222222222222222222", seguimiento=Seguimiento.MANUAL
    )
    anterior = _expediente(
        db_session,
        org,
        "ANT-2004-001",
        tipo_identificador=TipoIdentificador.RADICADO_ANTERIOR,
    )
    inactivo = _expediente(db_session, org, "33333333333333333333333", activo=False)
    f = FuenteFalsa()
    resumen = _correr(db_session, engine, f)

    assert f.llamadas_resolver == [RADICADO]
    assert resumen.revisados == 1 and resumen.no_consultables == 1  # el `anterior`
    assert _revisiones(db_session, bueno)
    for otro in (manual, anterior, inactivo):
        assert _revisiones(db_session, otro) == []


def test_circuito_abierto_marca_el_resto_no_verificado_sin_tocar_la_red(
    db_session, engine, org
):
    a = _expediente(db_session, org)
    b = _expediente(db_session, org, "44444444444444444444444")
    f = FuenteFalsa()
    f.abierto = True
    resumen = _correr(db_session, engine, f)

    assert f.llamadas_resolver == [] and f.llamadas_consultar == []
    for exp in (a, b):
        (rev,) = _revisiones(db_session, exp)
        assert rev.resultado == ResultadoRevision.NO_VERIFICADO
        assert "circuito abierto" in rev.detalle
    assert resumen.circuito_abierto
    assert resumen.por_resultado == {ResultadoRevision.NO_VERIFICADO: 2}


def test_una_excepcion_inesperada_no_frena_la_corrida(db_session, engine, org):
    a = _expediente(db_session, org)
    b = _expediente(db_session, org, "44444444444444444444444")
    f = FuenteFalsa()
    f.encontrados[RADICADO] = [_encontrado(100)]
    f.respuestas[100] = KeyError("forma inesperada")  # se lanza desde `consultar`
    # `consultar` lanza una excepción que no es ErrorFuente.
    _correr(db_session, engine, f)

    (rev_a,) = _revisiones(db_session, a)
    (rev_b,) = _revisiones(db_session, b)
    assert rev_a.resultado == ResultadoRevision.NO_VERIFICADO
    assert "error interno: KeyError" in rev_a.detalle
    assert rev_b.resultado == ResultadoRevision.NO_ENCONTRADO  # b sí se revisó


def test_lock_de_corrida_unica(engine):
    with revisor.lock_de_corrida(engine):
        with pytest.raises(CorridaEnCurso):
            with revisor.lock_de_corrida(engine):
                pass
    with revisor.lock_de_corrida(engine):  # y se suelta al terminar
        pass


def test_corrida_con_el_lock_tomado_no_escribe_nada(db_session, engine, org):
    exp = _expediente(db_session, org)
    f = FuenteFalsa()
    with revisor.lock_de_corrida(engine):
        with pytest.raises(CorridaEnCurso):
            _correr(db_session, engine, f)
    assert _revisiones(db_session, exp) == [] and f.llamadas_resolver == []


# -- vuelta a `resolver` ---------------------------------------------------------


def test_envio_a_otro_despacho_remite_el_proceso_y_da_de_alta_el_nuevo(
    db_session, engine, org
):
    exp = _expediente(db_session, org)
    f = FuenteFalsa()
    f.encontrados[RADICADO] = [_encontrado(100)]
    f.respuestas[100] = _con([_act(1)])
    _correr(db_session, engine, f)
    f.llamadas_resolver.clear()

    f.respuestas[100] = _con(
        [_act(2, 2, tipo="ENVÍO A OTROS DESPACHOS", anotacion="Envía a otro despacho")]
    )
    f.encontrados[RADICADO] = [_encontrado(100), _encontrado(300)]
    f.respuestas[300] = _con([_act(50)])
    _correr(db_session, engine, f)

    assert f.llamadas_resolver == [RADICADO]
    estados = {p.id_externo: p.estado for p in _procesos(db_session, exp)}
    assert estados == {100: EstadoProcesoFuente.REMITIDO, 300: EstadoProcesoFuente.ACTIVO}
    assert _revisiones(db_session, exp)[-1].resultado == ResultadoRevision.CON_NOVEDAD
    # El proceso nuevo se consultó de cero.
    assert f.llamadas_consultar[-1][0] == 300 and f.llamadas_consultar[-1][1] is None

    # Siguiente corrida: el remitido ya no se consulta; el nuevo sí.
    f.llamadas_consultar.clear()
    f.respuestas[300] = ConsultaProceso(
        ResultadoConsulta.SIN_CAMBIOS, datetime(2026, 10, 2, tzinfo=ZONA)
    )
    _correr(db_session, engine, f)
    assert [c[0] for c in f.llamadas_consultar] == [300]


def test_todos_remitidos_sin_destino_resuelve_cada_corrida(db_session, engine, org):
    _expediente(db_session, org)
    f = FuenteFalsa()
    f.encontrados[RADICADO] = [_encontrado(100)]
    f.respuestas[100] = _con([_act(1, 1, tipo="ENVÍO A OTROS DESPACHOS")])
    _correr(db_session, engine, f)  # línea base ya remitida
    f.llamadas_resolver.clear()
    _correr(db_session, engine, f)
    assert f.llamadas_resolver == [RADICADO]


def test_quietud_vuelve_a_resolver_y_sin_quietud_no(db_session, engine, org):
    _expediente(db_session, org)
    f = FuenteFalsa()
    f.encontrados[RADICADO] = [_encontrado(100)]
    f.respuestas[100] = _con([_act(1)], ultima=AHORA - timedelta(days=40))
    _correr(db_session, engine, f)
    f.llamadas_resolver.clear()
    f.respuestas[100] = ConsultaProceso(
        ResultadoConsulta.SIN_CAMBIOS, AHORA - timedelta(days=40)
    )

    # dias_quietud=1: la ranura determinista siempre coincide.
    _correr(db_session, engine, f, dias_quietud=1)
    assert f.llamadas_resolver == [RADICADO]

    f.llamadas_resolver.clear()
    f.respuestas[100] = ConsultaProceso(ResultadoConsulta.SIN_CAMBIOS, AHORA - timedelta(days=40))
    _correr(db_session, engine, f, dias_quietud=60)  # 40 días < 60: no está quieto
    assert f.llamadas_resolver == []


# -- zonas y utilidades ----------------------------------------------------------


def test_fechas_sin_zona_se_toman_como_colombia_y_se_guardan_en_utc(db_session, engine, org):
    _expediente(db_session, org)
    f = FuenteFalsa()
    f.encontrados[RADICADO] = [_encontrado(100)]
    f.respuestas[100] = _con(
        [_act(1, fecha=datetime(2026, 10, 1, 8, 0))],  # naive
        ultima=datetime(2026, 10, 2, 8, 0),
    )
    _correr(db_session, engine, f)

    a = db_session.execute(select(Actuacion)).scalar_one()
    assert a.fecha_actuacion == datetime(2026, 10, 1, 13, 0, tzinfo=timezone.utc)
    p = db_session.execute(select(ProcesoFuente)).scalar_one()
    assert p.ultima_actualizacion_fuente == datetime(2026, 10, 2, 13, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "tipo, anotacion, esperado",
    [
        ("ENVÍO A OTROS DESPACHOS", None, True),
        ("Otra", "Proceso finalizado por: Envía a otro despacho", True),
        ("Envio a otro despacho", None, True),
        ("Recepción memorial", "MEMORIAL IMPULSO PROCESAL", False),
        ("Auto", "ordena enviar el oficio a otras entidades", False),
    ],
)
def test_detecta_envio_a_otro_despacho(tipo, anotacion, esperado):
    assert es_envio_a_otro_despacho(tipo, anotacion) is esperado
