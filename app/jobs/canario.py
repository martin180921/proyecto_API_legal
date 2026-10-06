"""Canario de la fuente (Etapa Procesamiento; condición de entrada del spike P4).

    python -m app.jobs.canario

Los fixtures grabados **no** detectan que la Rama cambió la forma de su API:
protegen contra regresiones propias y seguirán en verde mientras producción se
cae. Esto sí: cada día consulta un radicado conocido (`CANARIO_RADICADO`) con
el conector real y comprueba que

1. `resolver` devuelve al menos un proceso (los tres endpoints que usa el
   revisor pasan por la validación pydantic del conector: otra forma →
   `RespuestaInvalida`),
2. `consultar` sobre el primero, sin nada visto, devuelve actuaciones.

Son ~4 peticiones (búsqueda, detalle y las páginas de actuaciones), con un
conector propio y su propio circuit breaker: un canario no comparte estado con
la corrida. No toca la base de datos ni escribe nada.

Código de salida: `0` bien; `1` falló, con la causa en el log (nivel ERROR).
Fallo del canario → aviso a **Martin, no al abogado**: no hay canal de aviso
propio todavía, así que el aviso es el cron en rojo de Railway y su log. Hay
que programarlo unos minutos **antes** de la revisión diaria, para saber que la
Rama cambió antes de que la corrida marque medio inventario `no_verificado`.
Un canario en rojo por «ya no existe» puede significar que el radicado se dio
de baja, no que la Rama cambió: léase el motivo.
"""
from __future__ import annotations

import logging
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass

from app.connectors.base import ErrorFuente, EstadoVisto, FuenteConsulta
from app.connectors.rama_judicial import RamaJudicial
from app.core.config import settings
from app.core.logging import configure_logging

logger = logging.getLogger("api_legal.canario")

_RADICADO = re.compile(r"\d{23}")


@dataclass(frozen=True)
class ResultadoCanario:
    ok: bool
    motivo: str  # qué pasó; si `ok`, un resumen
    procesos: int = 0
    actuaciones: int = 0


def verificar(fuente: FuenteConsulta, radicado: str) -> ResultadoCanario:
    if not _RADICADO.fullmatch(radicado):
        return ResultadoCanario(False, "CANARIO_RADICADO no es un radicado de 23 dígitos")
    try:
        procesos = fuente.resolver(radicado)
        if not procesos:
            return ResultadoCanario(
                False, "resolver devolvió [] para el radicado del canario (¿ya no existe?)"
            )
        consulta = fuente.consultar(
            procesos[0].id_externo, EstadoVisto(None, frozenset())
        )
    except ErrorFuente as e:
        return ResultadoCanario(False, f"{type(e).__name__}: {e}")
    if not consulta.actuaciones_nuevas:
        return ResultadoCanario(
            False,
            "consultar no devolvió actuaciones de un proceso que las tiene",
            procesos=len(procesos),
        )
    return ResultadoCanario(
        True,
        "la fuente responde con la forma esperada",
        procesos=len(procesos),
        actuaciones=len(consulta.actuaciones_nuevas),
    )


def _conector_por_defecto() -> FuenteConsulta:
    return RamaJudicial(contacto=settings.contacto_fuente)


def correr(
    *,
    crear_fuente: Callable[[], FuenteConsulta] = _conector_por_defecto,
    radicado: str | None = None,
) -> int:
    radicado = radicado or settings.canario_radicado
    try:
        fuente = crear_fuente()
    except Exception:  # noqa: BLE001
        logger.exception("canario: no se pudo crear el conector")
        return 1
    try:
        resultado = verificar(fuente, radicado)
    except Exception:  # noqa: BLE001 — lo inesperado también es una alarma
        logger.exception("canario: error inesperado")
        return 1
    finally:
        fuente.close()

    datos = {"procesos": resultado.procesos, "actuaciones": resultado.actuaciones}
    if resultado.ok:
        logger.info(f"canario: {resultado.motivo}", extra=datos)
        return 0
    logger.error(f"canario: FALLÓ: {resultado.motivo}", extra=datos)
    return 1


def main() -> int:
    configure_logging()
    return correr()


if __name__ == "__main__":
    sys.exit(main())
