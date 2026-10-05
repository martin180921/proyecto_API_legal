import dataclasses
from datetime import datetime

import pytest

from app.connectors.base import (
    ActuacionNormalizada,
    ConsultaProceso,
    ErrorFuente,
    EstadoVisto,
    FuenteConsulta,
    FuenteNoDisponible,
    FuenteRechazo,
    ProcesoEncontrado,
    ProcesoNoEncontrado,
    RespuestaInvalida,
    ResultadoConsulta,
)
from app.models.proceso_fuente import FuenteProceso


def _actuacion(**cambios):
    datos = dict(
        id_externo=2694826740,
        consecutivo=55,
        fecha_actuacion=datetime(2026, 4, 7),
        tipo="Recepción memorial",
        anotacion=None,
        fecha_inicial=None,
        fecha_final=None,
        fecha_registro=datetime(2026, 4, 7),
        con_documentos=False,
        crudo={"idRegActuacion": 2694826740},
    )
    datos.update(cambios)
    return ActuacionNormalizada(**datos)


def test_la_interfaz_no_se_puede_instanciar():
    with pytest.raises(TypeError):
        FuenteConsulta()


def test_una_fuente_incompleta_no_se_puede_instanciar():
    class SoloResolver(FuenteConsulta):
        fuente = FuenteProceso.RAMA_JUDICIAL

        def resolver(self, identificador):
            return []

    with pytest.raises(TypeError):
        SoloResolver()


def test_una_fuente_completa_funciona_sin_base_de_datos():
    class Falsa(FuenteConsulta):
        fuente = FuenteProceso.RAMA_JUDICIAL

        def resolver(self, identificador):
            return []

        def consultar(self, id_externo, desde):
            return ConsultaProceso(ResultadoConsulta.SIN_CAMBIOS, None)

    fuente = Falsa()
    assert fuente.resolver("11001400300520210036900") == []
    assert fuente.consultar(1, None).actuaciones_nuevas == ()


def test_los_datos_son_inmutables():
    with pytest.raises(dataclasses.FrozenInstanceError):
        _actuacion().anotacion = "otra"


def test_el_comparador_usa_id_externo_no_el_crudo():
    # `crudo` queda fuera de la igualdad: dos lecturas de la misma actuación
    # son la misma aunque el JSON original gane un campo.
    assert _actuacion(crudo={"a": 1}) == _actuacion(crudo={"a": 1, "nuevo": 2})
    assert _actuacion(id_externo=1) != _actuacion(id_externo=2)


def test_proceso_encontrado_admite_id_mayor_a_int32():
    # idProceso real del spike P4 (C.2).
    p = ProcesoEncontrado(
        id_externo=3290051731,
        id_conexion=320,
        despacho="Juzgado",
        departamento="Bogotá",
        fecha_ultima_actuacion=None,
        es_privado=False,
        crudo={},
    )
    assert p.id_externo > 2**31 - 1


def test_estado_visto_es_congelado():
    visto = EstadoVisto(None, frozenset({1, 2}))
    assert 1 in visto.ids_actuaciones_vistas
    with pytest.raises(dataclasses.FrozenInstanceError):
        visto.ultima_actualizacion = datetime.now()


@pytest.mark.parametrize(
    "error", [FuenteNoDisponible, FuenteRechazo, RespuestaInvalida, ProcesoNoEncontrado]
)
def test_todo_fallo_es_error_fuente(error):
    # El revisor captura `ErrorFuente` y registra `no_verificado`.
    assert issubclass(error, ErrorFuente)
