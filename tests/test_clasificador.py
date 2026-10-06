"""Clasificador por reglas (regla 5). Los casos reales salen de las actuaciones
del spike P4 (fixtures y notas de la revisión senior)."""
import pytest

from app.services.clasificador import TipoActuacion as T
from app.services.clasificador import clasificar


@pytest.mark.parametrize(
    "tipo, anotacion, esperado",
    [
        ("Fijacion estado", "ACTUACIÓN REGISTRADA", T.ESTADO),
        ("POR ESTADO", None, T.ESTADO),
        ("Fijación en lista", None, T.FIJACION_EN_LISTA),
        ("FIJACION TRASLADO EN LISTA", None, T.FIJACION_EN_LISTA),
        ("Traslado excepciones", None, T.TRASLADO),
        ("Sentencia de primera instancia", None, T.SENTENCIA),
        ("AUDIENCIA INICIAL", None, T.AUDIENCIA),
        ("Auto libra mandamiento ejecutivo", None, T.MANDAMIENTO_DE_PAGO),
        ("Auto admite demanda", None, T.ADMISION),
        ("Auto inadmite demanda", None, T.INADMISION),
        ("Archivo definitivo", None, T.ARCHIVO),
        ("Requerimiento", None, T.REQUERIMIENTO),
        ("Auto requiere a la parte", None, T.REQUERIMIENTO),
        ("Auto fija fecha audiencia", None, T.AUDIENCIA),
        ("Auto de archivo", None, T.ARCHIVO),
    ],
)
def test_clasifica_por_el_tipo(tipo, anotacion, esperado):
    assert clasificar(tipo, anotacion) is esperado


def test_inadmite_no_se_confunde_con_admite():
    assert clasificar("Auto inadmite demanda") is T.INADMISION
    assert clasificar("AUTO INADMISORIO") is T.INADMISION


def test_tildes_y_mayusculas_no_importan():
    assert clasificar("Fijación Estado") is T.ESTADO
    assert clasificar("SENTENCIA") is T.SENTENCIA


def test_auto_generico_mira_la_anotacion():
    assert clasificar("Auto", "ordena correr traslado a la parte demandada") is T.TRASLADO
    assert clasificar("Auto", "ordena seguir adelante la ejecución") is T.AUTO
    assert clasificar("Auto", None) is T.AUTO


def test_un_tipo_que_no_es_auto_no_consulta_la_anotacion():
    # Un memorial que menciona una audiencia sigue siendo un memorial.
    assert clasificar("Recepción memorial", "SOLICITA AUDIENCIA Y TRASLADO") is T.OTRO
    assert clasificar("Al despacho", "para sentencia") is T.OTRO


def test_lo_que_no_encaja_es_otro():
    assert clasificar("Recepción memorial", "MEMORIAL IMPULSO PROCESAL. AVRH") is T.OTRO
    assert clasificar("", None) is T.OTRO
