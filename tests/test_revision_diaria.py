"""Job diario: código de salida y cierre del conector. La lógica de la corrida
se prueba en `test_revisor.py`; aquí, lo que el job añade."""
import logging

from sqlalchemy import select

from app.jobs.revision_diaria import correr
from app.models.revision import Revision, ResultadoRevision
from app.services import revisor
from tests.test_revisor import RADICADO, FuenteFalsa, _encontrado, _expediente, org  # noqa: F401


class FuenteCierra(FuenteFalsa):
    cerrada = False

    def close(self):
        self.cerrada = True


def _correr(db, engine, fuente):
    return correr(crear_fuente=lambda: fuente, session_factory=lambda: db, motor=engine)


def test_corrida_normal_sale_con_0_y_cierra_el_conector(db_session, engine, org, caplog):  # noqa: F811
    exp = _expediente(db_session, org)
    f = FuenteCierra()
    with caplog.at_level(logging.INFO):
        assert _correr(db_session, engine, f) == 0
    assert f.cerrada
    assert db_session.execute(
        select(Revision.resultado).where(Revision.expediente_id == exp)
    ).scalar_one() == ResultadoRevision.NO_ENCONTRADO
    assert "corrida terminada" in caplog.text


def test_circuito_abierto_sale_con_1(db_session, engine, org):  # noqa: F811
    _expediente(db_session, org)
    f = FuenteCierra()
    f.abierto = True
    assert _correr(db_session, engine, f) == 1
    assert f.cerrada


def test_con_el_lock_tomado_sale_con_0_sin_escribir(db_session, engine, org):  # noqa: F811
    exp = _expediente(db_session, org)
    f = FuenteCierra()
    with revisor.lock_de_corrida(engine):
        assert _correr(db_session, engine, f) == 0
    assert f.cerrada
    assert db_session.execute(select(Revision).where(Revision.expediente_id == exp)).first() is None


def test_un_fallo_al_crear_el_conector_sale_con_1(db_session, engine):
    def mal():
        raise RuntimeError("sin conector")

    assert correr(crear_fuente=mal, session_factory=lambda: db_session, motor=engine) == 1


def test_un_fallo_de_la_corrida_sale_con_1_y_cierra_el_conector(db_session, engine, monkeypatch):
    f = FuenteCierra()

    def revienta(*a, **k):
        raise RuntimeError("base caída")

    monkeypatch.setattr("app.jobs.revision_diaria.ejecutar_corrida", revienta)
    assert _correr(db_session, engine, f) == 1
    assert f.cerrada


def test_main_con_limite_invalido_sale_con_error():
    import pytest
    from app.jobs.revision_diaria import main

    with pytest.raises(SystemExit):
        main(["--limite", "0"])
