"""Interfaz de las fuentes externas de consulta de procesos (Etapa
Procesamiento, reglas 2 y 3). El conector **no toca la base de datos**: recibe
y devuelve datos, así que se prueba con fixtures y no depende de Postgres.

Dos operaciones, porque B.1-bis separó lo que antes era una sola
([[Relación expediente ↔ proceso de la fuente — B.1-bis]]):

- `resolver(identificador)`: búsqueda por radicado. Un radicado puede devolver
  varios procesos, y un proceso remitido a otro despacho continúa bajo otro
  (spike P4, C.1). Lista vacía = «no encontrado», un resultado válido, no un
  error.
- `consultar(id_externo, desde)`: detalle + actuaciones nuevas de **un**
  proceso.

Contrato de errores — lo que sostiene los cuatro estados de `Revision`
(condición de entrada 3 del spike): un fallo de red, un 429/403, un JSON con
otra forma o un circuito abierto se **lanzan** como `ErrorFuente`; el revisor
los registra como `no_verificado`. Ningún conector devuelve «sin cambios»
ante un fallo: eso sería afirmar una revisión que no hubo.

El comparador de la regla 4 va sobre `id_externo` de la actuación
(`idRegActuacion`), no sobre fechas ni consecutivos: los consecutivos son por
proceso y reinician si se remite, y `fechaRegistro` puede ir trece meses por
detrás de `fechaActuacion` (spike P4, condición de entrada 2).
"""
from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.models.proceso_fuente import FuenteProceso


class ErrorFuente(Exception):
    """La fuente no pudo verificarse. El revisor lo registra como
    `no_verificado`, nunca como `sin_novedad`."""


class FuenteNoDisponible(ErrorFuente):
    """Red, timeout, 5xx o circuit breaker abierto."""


class FuenteRechazo(ErrorFuente):
    """429/403 u otra señal de bloqueo. Debe abrir el circuit breaker: una IP
    bloqueada por un ente estatal no se revierte con un ticket."""


class RespuestaInvalida(ErrorFuente):
    """El JSON no tiene la forma del contrato. Es lo que convierte un cambio
    de la fuente en un aviso en vez de en tranquilidad falsa."""


class ProcesoNoEncontrado(ErrorFuente):
    """`consultar` sobre un `id_externo` que la fuente ya no reconoce. Distinto
    de `resolver` con lista vacía: aquí el proceso existía (estado
    `desaparecido` en `procesos_fuente`)."""


@dataclass(frozen=True)
class ProcesoEncontrado:
    id_externo: int
    id_conexion: int | None
    despacho: str | None
    departamento: str | None
    fecha_ultima_actuacion: datetime | None
    es_privado: bool
    crudo: dict[str, Any] = field(compare=False, repr=False)


@dataclass(frozen=True)
class ActuacionNormalizada:
    id_externo: int  # idRegActuacion: la clave del comparador (regla 4)
    consecutivo: int  # consActuacion; solo informativo, reinicia al remitir
    fecha_actuacion: datetime
    tipo: str  # `actuacion` en la fuente
    anotacion: str | None
    # Siempre, nunca condicionados al tipo de actuación (spike P4, C.3): salen
    # también de «Fijación edicto emplazatorio» y «POR ESTADO».
    fecha_inicial: datetime | None
    fecha_final: datetime | None
    fecha_registro: datetime | None
    con_documentos: bool
    crudo: dict[str, Any] = field(compare=False, repr=False)


@dataclass(frozen=True)
class EstadoVisto:
    """Lo que el revisor ya sabe de un proceso; `None` en `consultar` = primera
    vez, se pagina entero."""

    ultima_actualizacion: datetime | None
    ids_actuaciones_vistas: frozenset[int]


class ResultadoConsulta(str, enum.Enum):
    # `ultima_actualizacion` igual: no se pidieron actuaciones (C.5).
    SIN_CAMBIOS = "sin_cambios"
    # Cambió y hay al menos una actuación nueva.
    CON_ACTUACIONES = "con_actuaciones"
    # Cambió, pero nada nuevo en la página leída.
    CAMBIO_SIN_ACTUACIONES = "cambio_sin_actuaciones"


@dataclass(frozen=True)
class ConsultaProceso:
    resultado: ResultadoConsulta
    ultima_actualizacion: datetime | None
    # Más recientes primero, como las entrega la fuente; solo las no vistas.
    actuaciones_nuevas: tuple[ActuacionNormalizada, ...] = ()


class FuenteConsulta(ABC):
    fuente: FuenteProceso

    @property
    def circuito_abierto(self) -> bool:
        """`True` si el conector ya decidió no salir más a la red en esta
        corrida (429/403, fallos seguidos). El revisor lo consulta para marcar
        el resto de la corrida como `no_verificado` sin intentarlo."""
        return False

    def close(self) -> None:
        """Libera lo que el conector tenga abierto (cliente HTTP). El job lo
        llama al terminar la corrida."""

    @abstractmethod
    def resolver(self, identificador: str) -> list[ProcesoEncontrado]:
        """Procesos que la fuente asocia al identificador. `[]` si no hay."""

    @abstractmethod
    def consultar(
        self, id_externo: int, desde: EstadoVisto | None
    ) -> ConsultaProceso:
        """Detalle + actuaciones nuevas de un proceso. Lanza `ErrorFuente` ante
        cualquier fallo; nunca devuelve `SIN_CAMBIOS` por no haber podido
        verificar."""
