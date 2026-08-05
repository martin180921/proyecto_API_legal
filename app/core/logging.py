"""Logging estructurado (JSON) desde el primer endpoint.

Tarea de la Semana 1 del horario: "Logs estructurados y metricas basicas —
ver una peticion real en el log".
"""
import logging
import sys

from pythonjsonlogger.json import JsonFormatter

from app.core.config import settings


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    formatter = JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level)
