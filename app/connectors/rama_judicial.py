"""Conector de la Consulta de Procesos de la Rama Judicial (Etapa
Procesamiento, reglas 2 y 3).

El contrato y la disciplina de salida mandan desde
[[Contrato real de la API de Rama Judicial — spike P4]] (revisión senior del
2026-09-11); las formas de respuesta de `tests/fixtures/rama_judicial/` se
grabaron en vivo el 2026-10-05 (con nombres y anotaciones redactados).

Disciplina de salida, por qué cada cosa:

- ~1 petición por segundo y sin concurrencia (`intervalo`): son ~250-300
  peticiones cada mañana contra un ente estatal sin límites declarados.
- Una instancia = una corrida. El circuit breaker no se cierra solo: ante un
  429/403, o `max_fallos_seguidos` fallos de red/5xx seguidos, todo lo que
  queda de la corrida se rechaza sin salir a la red. Una IP bloqueada no se
  revierte con un ticket; reintentar a ciegas lo empeora.
- Timeouts de conexión y lectura por separado, y un presupuesto total por
  operación (`presupuesto`): un expediente no puede comerse la corrida.
- Reintentos solo ante fallo de transporte o 5xx (todas las peticiones son
  `GET`, idempotentes), con espera creciente, y nunca ante un 4xx.
- `User-Agent` identificable, no un navegador fingido.

Todo fallo se lanza como `ErrorFuente`; el revisor lo registra como
`no_verificado`. Una respuesta con otra forma es `RespuestaInvalida`, jamás un
«sin cambios»: así un cambio de la Rama se ve como aviso, no como tranquilidad.

Las fechas se devuelven con zona `-05:00` (Colombia no tiene horario de
verano): la fuente las da sin zona, y `procesos_fuente` guarda `timestamptz`,
así que comparar un naive con un aware daría siempre «cambió».
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.connectors.base import (
    ActuacionNormalizada,
    ConsultaProceso,
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

BASE_URL = "https://consultaprocesos.ramajudicial.gov.co:448/api/v2"
USER_AGENT = "api-legal-revisor/1.0"
ZONA = timezone(timedelta(hours=-5))
_RADICADO = re.compile(r"\d{23}")
_RECHAZO = {403, 429}


def _fecha(valor: datetime | None) -> datetime | None:
    if valor is None:
        return None
    return valor.replace(tzinfo=ZONA) if valor.tzinfo is None else valor


class _Paginacion(BaseModel):
    model_config = ConfigDict(extra="ignore")
    cantidad_paginas: int = Field(alias="cantidadPaginas")
    pagina: int


class _Proceso(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id_proceso: int = Field(alias="idProceso")
    id_conexion: int | None = Field(default=None, alias="idConexion")
    despacho: str | None = None
    departamento: str | None = None
    fecha_ultima_actuacion: datetime | None = Field(
        default=None, alias="fechaUltimaActuacion"
    )
    es_privado: bool = Field(default=False, alias="esPrivado")


class _Busqueda(BaseModel):
    model_config = ConfigDict(extra="ignore")
    procesos: list[dict[str, Any]]
    paginacion: _Paginacion | None = None


class _Detalle(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ultima_actualizacion: datetime = Field(alias="ultimaActualizacion")


class _Actuacion(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id_reg_actuacion: int = Field(alias="idRegActuacion")
    cons_actuacion: int = Field(alias="consActuacion")
    fecha_actuacion: datetime = Field(alias="fechaActuacion")
    actuacion: str
    anotacion: str | None = None
    fecha_inicial: datetime | None = Field(default=None, alias="fechaInicial")
    fecha_final: datetime | None = Field(default=None, alias="fechaFinal")
    fecha_registro: datetime | None = Field(default=None, alias="fechaRegistro")
    con_documentos: bool = Field(default=False, alias="conDocumentos")


class _Actuaciones(BaseModel):
    model_config = ConfigDict(extra="ignore")
    actuaciones: list[dict[str, Any]]
    paginacion: _Paginacion | None = None


class RamaJudicial(FuenteConsulta):
    fuente = FuenteProceso.RAMA_JUDICIAL

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        base_url: str = BASE_URL,
        intervalo: float = 1.0,
        reintentos: int = 2,
        espera_reintento: float = 2.0,
        max_fallos_seguidos: int = 5,
        presupuesto: float = 60.0,
        max_paginas: int = 50,
        reloj: Callable[[], float] = time.monotonic,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        self._base = base_url.rstrip("/")
        self._intervalo = intervalo
        self._reintentos = reintentos
        self._espera = espera_reintento
        self._max_fallos = max_fallos_seguidos
        self._presupuesto = presupuesto
        self._max_paginas = max_paginas
        self._reloj = reloj
        self._dormir = dormir
        self._ultima_peticion: float | None = None
        self._fallos_seguidos = 0
        self._abierto: str | None = None
        self._limite: float | None = None

    @property
    def circuito_abierto(self) -> bool:
        return self._abierto is not None

    def close(self) -> None:
        self._client.close()

    # -- operaciones públicas ------------------------------------------------

    def resolver(self, identificador: str) -> list[ProcesoEncontrado]:
        # Condición de entrada 4 del spike: el único endpoint de búsqueda
        # acepta 23 dígitos. Filtrar antes es del revisor; llegar aquí con
        # otra cosa es un error de programación, no un fallo de la fuente.
        if not _RADICADO.fullmatch(identificador):
            raise ValueError("el identificador debe ser un radicado de 23 dígitos")
        self._iniciar_operacion()
        encontrados: list[ProcesoEncontrado] = []
        pagina = 1
        while True:
            datos = self._get(
                "/Procesos/Consulta/NumeroRadicacion",
                {"numero": identificador, "SoloActivos": "false", "pagina": pagina},
            )
            busqueda = self._validar(_Busqueda, datos)
            for crudo in busqueda.procesos:
                p = self._validar(_Proceso, crudo)
                encontrados.append(
                    ProcesoEncontrado(
                        id_externo=p.id_proceso,
                        id_conexion=p.id_conexion,
                        despacho=_limpio(p.despacho),
                        departamento=_limpio(p.departamento),
                        fecha_ultima_actuacion=_fecha(p.fecha_ultima_actuacion),
                        es_privado=p.es_privado,
                        crudo=crudo,
                    )
                )
            if not self._hay_mas(busqueda.paginacion, pagina):
                return encontrados
            pagina += 1

    def consultar(
        self, id_externo: int, desde: EstadoVisto | None
    ) -> ConsultaProceso:
        self._iniciar_operacion()
        detalle = self._validar(
            _Detalle, self._get(f"/Proceso/Detalle/{id_externo}", None, id_externo)
        )
        ultima = _fecha(detalle.ultima_actualizacion)
        if desde and desde.ultima_actualizacion and desde.ultima_actualizacion == ultima:
            # C.5 del spike: nada cambió, no se piden actuaciones.
            return ConsultaProceso(ResultadoConsulta.SIN_CAMBIOS, ultima)

        vistas = desde.ids_actuaciones_vistas if desde else frozenset()
        nuevas: list[ActuacionNormalizada] = []
        pagina = 1
        while True:
            datos = self._get(
                f"/Proceso/Actuaciones/{id_externo}", {"pagina": pagina}, id_externo
            )
            lote = self._validar(_Actuaciones, datos)
            for crudo in lote.actuaciones:
                a = self._validar(_Actuacion, crudo)
                if a.id_reg_actuacion in vistas:
                    # Orden descendente (C.5): lo que sigue ya se vio.
                    return self._resultado(ultima, nuevas)
                nuevas.append(
                    ActuacionNormalizada(
                        id_externo=a.id_reg_actuacion,
                        consecutivo=a.cons_actuacion,
                        fecha_actuacion=_fecha(a.fecha_actuacion),
                        tipo=a.actuacion,
                        anotacion=a.anotacion,
                        fecha_inicial=_fecha(a.fecha_inicial),
                        fecha_final=_fecha(a.fecha_final),
                        fecha_registro=_fecha(a.fecha_registro),
                        con_documentos=a.con_documentos,
                        crudo=crudo,
                    )
                )
            if not self._hay_mas(lote.paginacion, pagina):
                return self._resultado(ultima, nuevas)
            pagina += 1

    # -- internos -------------------------------------------------------------

    @staticmethod
    def _resultado(
        ultima: datetime | None, nuevas: list[ActuacionNormalizada]
    ) -> ConsultaProceso:
        if nuevas:
            return ConsultaProceso(
                ResultadoConsulta.CON_ACTUACIONES, ultima, tuple(nuevas)
            )
        return ConsultaProceso(ResultadoConsulta.CAMBIO_SIN_ACTUACIONES, ultima)

    def _hay_mas(self, paginacion: _Paginacion | None, pagina: int) -> bool:
        if paginacion is None or pagina >= paginacion.cantidad_paginas:
            return False
        if pagina >= self._max_paginas:
            # Tope duro: un `cantidadPaginas` absurdo no puede dejar un bucle
            # pegándole a la fuente.
            raise RespuestaInvalida(f"más de {self._max_paginas} páginas")
        return True

    @staticmethod
    def _validar(modelo: type[BaseModel], datos: Any):
        try:
            return modelo.model_validate(datos)
        except ValidationError as e:
            raise RespuestaInvalida(
                f"{modelo.__name__}: {e.error_count()} error(es) de forma"
            ) from e

    def _iniciar_operacion(self) -> None:
        self._limite = self._reloj() + self._presupuesto

    def _get(
        self,
        ruta: str,
        params: dict[str, Any] | None,
        id_externo: int | None = None,
    ) -> Any:
        intentos = self._reintentos + 1
        for intento in range(intentos):
            if self._abierto:
                raise FuenteNoDisponible(f"circuito abierto: {self._abierto}")
            if self._limite is not None and self._reloj() >= self._limite:
                raise FuenteNoDisponible("presupuesto de tiempo agotado")
            self._esperar_turno()
            try:
                resp = self._client.get(self._base + ruta, params=params)
            except httpx.TransportError as e:
                self._registrar_fallo(f"{type(e).__name__}")
                if intento + 1 == intentos:
                    raise FuenteNoDisponible(f"{ruta}: {type(e).__name__}") from e
                self._dormir(self._espera * (intento + 1))
                continue

            if resp.status_code in _RECHAZO:
                self._abierto = f"HTTP {resp.status_code} en {ruta}"
                raise FuenteRechazo(self._abierto)
            if resp.status_code >= 500:
                self._registrar_fallo(f"HTTP {resp.status_code}")
                if intento + 1 == intentos:
                    raise FuenteNoDisponible(f"{ruta}: HTTP {resp.status_code}")
                self._dormir(self._espera * (intento + 1))
                continue
            if resp.status_code == 404 and id_externo is not None:
                self._fallos_seguidos = 0
                raise ProcesoNoEncontrado(f"idProceso {id_externo}")
            if resp.status_code != 200:
                # 400 y compañía: la fuente cambió o la petición es otra.
                # No se reintenta, y no cuenta contra el breaker.
                raise RespuestaInvalida(f"{ruta}: HTTP {resp.status_code}")
            try:
                datos = resp.json()
            except ValueError as e:
                raise RespuestaInvalida(f"{ruta}: cuerpo no es JSON") from e
            self._fallos_seguidos = 0
            return datos
        raise AssertionError("inalcanzable")  # pragma: no cover

    def _registrar_fallo(self, motivo: str) -> None:
        self._fallos_seguidos += 1
        if self._fallos_seguidos >= self._max_fallos:
            self._abierto = f"{self._fallos_seguidos} fallos seguidos ({motivo})"

    def _esperar_turno(self) -> None:
        ahora = self._reloj()
        if self._ultima_peticion is not None:
            falta = self._intervalo - (ahora - self._ultima_peticion)
            if falta > 0:
                self._dormir(falta)
                ahora = self._reloj()
        self._ultima_peticion = ahora


def _limpio(texto: str | None) -> str | None:
    # La fuente rellena con espacios al final («...BOGOTÁ »).
    return texto.strip() if texto else texto
