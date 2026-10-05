"""`Revision` y `Actuacion` (Etapa Procesamiento). Sin endpoints todavía: el
revisor (fuera de esta sesión) es quien las escribe. Aquí se prueba el modelo,
sus cuatro resultados y la tenancy compuesta (R.3)."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models.actuacion import Actuacion
from app.models.expediente import Expediente, Seguimiento, TipoIdentificador, TipoProceso
from app.models.organizacion import Organizacion
from app.models.proceso_fuente import EstadoProcesoFuente, FuenteProceso, ProcesoFuente
from app.models.revision import Revision, ResultadoRevision

AHORA = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def _organizacion(db, slug):
    org = Organizacion(nombre=f"Bufete {slug}", slug=slug)
    db.add(org)
    db.flush()
    return org


def _proceso(db, org, identificador="12345678901234567890123", id_externo=88326800):
    exp = Expediente(
        organizacion_id=org.id,
        identificador=identificador,
        tipo_identificador=TipoIdentificador.RADICADO_UNIFICADO,
        seguimiento=Seguimiento.AUTOMATICO,
        tipo_proceso=TipoProceso.CIVIL,
    )
    db.add(exp)
    db.flush()
    pf = ProcesoFuente(
        organizacion_id=org.id,
        expediente_id=exp.id,
        fuente=FuenteProceso.RAMA_JUDICIAL,
        id_externo=id_externo,
        es_privado=False,
        estado=EstadoProcesoFuente.ACTIVO,
    )
    db.add(pf)
    db.flush()
    return exp, pf


def _revision(db, exp, resultado=ResultadoRevision.CON_NOVEDAD, **kw):
    r = Revision(
        organizacion_id=exp.organizacion_id,
        expediente_id=exp.id,
        fuente=FuenteProceso.RAMA_JUDICIAL,
        resultado=resultado,
        **kw,
    )
    db.add(r)
    db.flush()
    return r


def _actuacion(pf, rev, id_externo=2694826740, **kw):
    datos = dict(
        organizacion_id=pf.organizacion_id,
        proceso_fuente_id=pf.id,
        revision_id=rev.id,
        id_externo=id_externo,
        consecutivo=55,
        fecha_actuacion=AHORA,
        tipo="Recepción memorial",
        con_documentos=False,
        crudo={"idRegActuacion": id_externo},
    )
    datos.update(kw)
    return Actuacion(**datos)


# -- Revision ---------------------------------------------------------------


@pytest.mark.parametrize("resultado", list(ResultadoRevision))
def test_revision_admite_los_cuatro_resultados(db_session, resultado):
    org = _organizacion(db_session, "b1")
    exp, _ = _proceso(db_session, org)
    r = _revision(db_session, exp, resultado)
    assert db_session.get(Revision, r.id).resultado is resultado
    assert r.revisado_en is not None  # lo pone la base de datos


def test_revision_no_verificado_guarda_el_motivo(db_session):
    org = _organizacion(db_session, "b1")
    exp, _ = _proceso(db_session, org)
    r = _revision(db_session, exp, ResultadoRevision.NO_VERIFICADO, detalle="HTTP 503")
    assert db_session.get(Revision, r.id).detalle == "HTTP 503"


def test_la_base_rechaza_un_resultado_fuera_de_los_cuatro(db_session):
    org = _organizacion(db_session, "b1")
    exp, _ = _proceso(db_session, org)
    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "INSERT INTO revisiones (id, organizacion_id, expediente_id, fuente, resultado) "
                "VALUES (gen_random_uuid(), :o, :e, 'rama_judicial', 'sin_novedad_falso')"
            ),
            {"o": org.id, "e": exp.id},
        )


def test_revision_de_expediente_de_otra_organizacion_falla(db_session):
    a = _organizacion(db_session, "a")
    b = _organizacion(db_session, "b")
    exp_a, _ = _proceso(db_session, a)
    db_session.add(
        Revision(
            organizacion_id=b.id,
            expediente_id=exp_a.id,
            fuente=FuenteProceso.RAMA_JUDICIAL,
            resultado=ResultadoRevision.SIN_NOVEDAD,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


# -- Actuacion --------------------------------------------------------------


def test_crear_actuacion_guarda_fechas_y_crudo(db_session):
    org = _organizacion(db_session, "b1")
    exp, pf = _proceso(db_session, org)
    rev = _revision(db_session, exp)
    inicio, fin = datetime(2026, 9, 2, tzinfo=timezone.utc), datetime(2026, 10, 14, tzinfo=timezone.utc)
    a = _actuacion(pf, rev, fecha_inicial=inicio, fecha_final=fin, anotacion="x")
    db_session.add(a)
    db_session.flush()
    db_session.expire_all()

    leida = db_session.get(Actuacion, a.id)
    assert leida.id_externo == 2694826740  # supera int32
    assert leida.fecha_inicial == inicio and leida.fecha_final == fin
    assert leida.crudo == {"idRegActuacion": 2694826740}


def test_la_misma_actuacion_dos_veces_en_un_proceso_falla(db_session):
    org = _organizacion(db_session, "b1")
    exp, pf = _proceso(db_session, org)
    rev = _revision(db_session, exp)
    db_session.add(_actuacion(pf, rev))
    db_session.flush()
    db_session.add(_actuacion(pf, rev))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_mismo_id_externo_en_dos_procesos_es_valido(db_session):
    # Los consecutivos reinician al remitir (C.1), y los ids son por proceso.
    org = _organizacion(db_session, "b1")
    exp, pf1 = _proceso(db_session, org)
    pf2 = ProcesoFuente(
        organizacion_id=org.id,
        expediente_id=exp.id,
        fuente=FuenteProceso.RAMA_JUDICIAL,
        id_externo=3290051731,
        es_privado=False,
        estado=EstadoProcesoFuente.ACTIVO,
    )
    db_session.add(pf2)
    db_session.flush()
    rev = _revision(db_session, exp)
    db_session.add_all([_actuacion(pf1, rev), _actuacion(pf2, rev)])
    db_session.flush()


def test_actuacion_con_proceso_de_otra_organizacion_falla(db_session):
    a = _organizacion(db_session, "a")
    b = _organizacion(db_session, "b")
    exp_a, pf_a = _proceso(db_session, a)
    exp_b, _ = _proceso(db_session, b, identificador="99999999999999999999999", id_externo=1)
    rev_b = _revision(db_session, exp_b)
    db_session.add(_actuacion(pf_a, rev_b, organizacion_id=b.id))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_actuacion_con_revision_de_otra_organizacion_falla(db_session):
    a = _organizacion(db_session, "a")
    b = _organizacion(db_session, "b")
    exp_a, pf_a = _proceso(db_session, a)
    exp_b, _ = _proceso(db_session, b, identificador="99999999999999999999999", id_externo=1)
    rev_b = _revision(db_session, exp_b)
    db_session.add(_actuacion(pf_a, rev_b))  # organizacion_id = a, revisión de b
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_actuacion_sin_revision_falla(db_session):
    org = _organizacion(db_session, "b1")
    exp, pf = _proceso(db_session, org)
    rev = _revision(db_session, exp)
    a = _actuacion(pf, rev)
    a.revision_id = None
    db_session.add(a)
    with pytest.raises(IntegrityError):
        db_session.flush()
