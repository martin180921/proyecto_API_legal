"""Job de la revisión diaria (Etapa Procesamiento, reglas 1 y 10).

    python -m app.jobs.revision_diaria [--limite N]

Pensado para el cron de Railway en días hábiles; la continuidad de la regla 10
la dan el propio cron y el registro de `revisiones`, no este módulo. Una
ejecución = una corrida: construye el conector (una instancia por corrida, su
circuit breaker no se cierra solo), llama a `ejecutar_corrida` y cierra.

Código de salida — es lo que hace visible un mal día en el panel de Railway:

- `0`: la corrida terminó. Incluye «otra corrida tiene el lock»: el cron
  solapó una ejecución lenta y esta se aparta sin escribir nada; no es un
  fallo.
- `1`: el circuito del conector se abrió (429/403 o fallos seguidos: parte de
  los expedientes quedó `no_verificado`) o hubo un error que impidió correr.
  Un cron que «va bien» mientras la Rama bloquea la IP es justo el silencio
  que este sistema existe para evitar.

Lo que una corrida dejó por expediente está en `revisiones`, agrupado por
`corrida_id`; esta salida solo resume.
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.connectors.base import FuenteConsulta
from app.connectors.rama_judicial import RamaJudicial
from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.core.logging import configure_logging
from app.services.revisor import CorridaEnCurso, ejecutar_corrida

logger = logging.getLogger("api_legal.revision_diaria")


def _conector_por_defecto() -> FuenteConsulta:
    return RamaJudicial(contacto=settings.contacto_fuente)


def correr(
    *,
    crear_fuente: Callable[[], FuenteConsulta] = _conector_por_defecto,
    session_factory: Callable[[], Session] = SessionLocal,
    motor: Engine = engine,
    limite: int | None = None,
) -> int:
    """Una corrida completa; devuelve el código de salida del proceso."""
    try:
        fuente = crear_fuente()
    except Exception:  # noqa: BLE001
        logger.exception("revision_diaria: no se pudo crear el conector")
        return 1
    try:
        resumen = ejecutar_corrida(session_factory, fuente, engine=motor, limite=limite)
    except CorridaEnCurso:
        logger.warning("revision_diaria: otra corrida tiene el lock; esta no corre")
        return 0
    except Exception:  # noqa: BLE001
        logger.exception("revision_diaria: la corrida falló")
        return 1
    finally:
        fuente.close()

    por_resultado = {r.value: n for r, n in resumen.por_resultado.items()}
    logger.log(
        logging.ERROR if resumen.circuito_abierto else logging.INFO,
        "revision_diaria: corrida terminada",
        extra={
            "corrida_id": str(resumen.corrida_id),
            "revisados": resumen.revisados,
            "por_resultado": por_resultado,
            "no_consultables": resumen.no_consultables,
            "circuito_abierto": resumen.circuito_abierto,
        },
    )
    return 1 if resumen.circuito_abierto else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Corrida de la revisión diaria")
    parser.add_argument(
        "--limite", type=int, default=None,
        help="revisar solo los N primeros expedientes (corridas de prueba a mano)",
    )
    args = parser.parse_args(argv)
    if args.limite is not None and args.limite < 1:
        parser.error("--limite debe ser >= 1")
    configure_logging()
    return correr(limite=args.limite)


if __name__ == "__main__":
    sys.exit(main())
