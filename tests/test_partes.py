"""`Parte` (A.2.2, Bloque A3): tabla estructurada de partes procesales, aparte
del texto libre de `Expediente.partes`. Sin endpoints en esta sesión — el
conector (fuera de alcance) es quien la llenará de verdad; aquí solo se
comprueba el modelo y su relación con `Expediente`."""
import uuid

import pytest

from app.models.expediente import Expediente, Seguimiento, TipoIdentificador, TipoProceso
from app.models.organizacion import Organizacion
from app.models.parte import OrigenParte, Parte


@pytest.fixture()
def expediente(db_session):
    organizacion = Organizacion(nombre="Bufete Infante", slug="bufete-infante")
    db_session.add(organizacion)
    db_session.flush()

    expediente = Expediente(
        organizacion_id=organizacion.id,
        identificador="12345678901234567890123",
        tipo_identificador=TipoIdentificador.RADICADO_UNIFICADO,
        seguimiento=Seguimiento.AUTOMATICO,
        tipo_proceso=TipoProceso.CIVIL,
    )
    db_session.add(expediente)
    db_session.flush()
    return expediente


def test_crear_parte_ligada_a_expediente_existente(db_session, expediente):
    parte = Parte(
        organizacion_id=expediente.organizacion_id,
        expediente_id=expediente.id,
        tipo="Demandante",
        nombre="Exporminas S.A.",
        identificacion="900123456-1",
        origen=OrigenParte.IMPORTACION,
    )
    db_session.add(parte)
    db_session.flush()

    assert parte.id is not None
    recuperada = db_session.get(Parte, parte.id)
    assert recuperada.expediente_id == expediente.id
    assert recuperada.organizacion_id == expediente.organizacion_id


def test_parte_sin_identificacion_es_valida(db_session, expediente):
    """`identificacion` es nullable — el spike de P4 documentó que
    `GET /Proceso/Sujetos/{idProceso}` la devuelve nula a veces."""
    parte = Parte(
        organizacion_id=expediente.organizacion_id,
        expediente_id=expediente.id,
        tipo="Demandado",
        nombre="Sacol S.A.S.",
        identificacion=None,
        origen=OrigenParte.CONECTOR,
    )
    db_session.add(parte)
    db_session.flush()

    assert parte.id is not None


def test_archivar_expediente_no_deja_partes_huerfanas(db_session, expediente):
    """El archivado de `Expediente` es lógico (`activo = False`), no un
    `DELETE`: sus `partes` siguen existiendo y ligadas, no huérfanas."""
    parte = Parte(
        organizacion_id=expediente.organizacion_id,
        expediente_id=expediente.id,
        tipo="Demandante",
        nombre="Exporminas S.A.",
        origen=OrigenParte.IMPORTACION,
    )
    db_session.add(parte)
    db_session.flush()

    expediente.activo = False
    db_session.flush()

    recuperada = db_session.get(Parte, parte.id)
    assert recuperada is not None
    assert recuperada.expediente_id == expediente.id


def test_parte_de_expediente_inexistente_falla(db_session, expediente):
    """Integridad referencial de verdad, mismo criterio que
    `tests/test_models.py::test_organizacion_inexistente_falla`."""
    from sqlalchemy.exc import IntegrityError

    parte = Parte(
        organizacion_id=expediente.organizacion_id,
        expediente_id=uuid.uuid4(),
        tipo="Demandante",
        nombre="Nadie",
        origen=OrigenParte.IMPORTACION,
    )
    db_session.add(parte)
    with pytest.raises(IntegrityError):
        db_session.flush()
