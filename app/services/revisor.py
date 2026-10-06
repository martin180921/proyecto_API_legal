"""Revisor: orquesta la revisión diaria (Etapa Procesamiento, reglas 1, 4, 9 y
10). **Un expediente = una unidad de trabajo** con su propia transacción: es la
costura que permite pasar después de un bucle a una cola.

Por cada expediente `automatico` y consultable, por cada `ProcesoFuente`
activo, llama a `consultar` con un `EstadoVisto` armado desde la base, y deja
**una `Revision` por expediente y fuente, siempre**, también cuando falla.

Lo que el conector no hace y el revisor sí (condiciones de entrada del spike
P4, [[Contrato real de la API de Rama Judicial — spike P4]]):

- **Lock de corrida única en base de datos**: `pg_try_advisory_lock` sobre una
  conexión que vive toda la corrida. Si el proceso muere, Postgres lo suelta
  solo; con una tabla de lock habría que limpiar locks huérfanos a mano. El
  cron de Railway puede solapar ejecuciones.
- **Filtro de consultables** (condición 4): `seguimiento = 'automatico'` **y**
  `tipo_identificador = 'radicado_unificado'` con 23 dígitos. Un `automatico`
  con `radicado_anterior` sería «no encontrado» para siempre. Se cuentan en
  `ResumenCorrida.no_consultables`, no se tragan en silencio.
- **`ErrorFuente` → `no_verificado`**, jamás `sin_novedad`. Si el circuito del
  conector se abre, el resto de la corrida se marca `no_verificado` sin salir a
  la red. Cualquier excepción inesperada de un expediente también (y no frena
  a los demás).
- **Zonas**: toda fecha se normaliza a UTC antes de guardar o comparar; una
  fecha sin zona se toma como hora de Colombia (-05:00, sin horario de verano).

Redes antes que escrituras: la lectura del estado y la escritura van en
transacciones cortas, y las llamadas a la fuente (lentas, ~1 req/s) ocurren
entre las dos, sin transacción abierta.

Cuándo se vuelve a `resolver` (da de alta los `idProceso` nuevos): el
expediente no tiene ningún proceso activo (nunca encontrado, o todos
remitidos); la última actuación de un proceso es un «envío a otro despacho»
(ese proceso pasa a `remitido`); o todos los procesos activos llevan
`DIAS_QUIETUD` días sin moverse. En el tercer caso no hay dónde guardar «cuándo
resolví por última vez» sin migración, así que se reparte por una ranura
determinista por expediente: a lo sumo una vez cada `DIAS_QUIETUD` días.

Línea base: la primera vez que se ve un expediente (sin ningún proceso en la
base) se carga su historial completo, pero eso no es «novedad» — el abogado ya
conoce ese expediente — y se registra `sin_novedad` con el detalle de la carga.
Los procesos que aparecen **después** (p. ej. tras una remisión) sí cuentan.
"""
from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.connectors.base import (
    ActuacionNormalizada,
    ConsultaProceso,
    ErrorFuente,
    EstadoVisto,
    FuenteConsulta,
    ProcesoEncontrado,
    ResultadoConsulta,
)
from app.models.actuacion import Actuacion
from app.models.expediente import Expediente, Seguimiento, TipoIdentificador
from app.models.proceso_fuente import EstadoProcesoFuente, ProcesoFuente
from app.models.revision import Revision, ResultadoRevision
from app.services.clasificador import normalizar

logger = logging.getLogger(__name__)

# Decidido por Martin el 2026-10-06.
DIAS_QUIETUD = 30

# Colombia no tiene horario de verano.
ZONA_COLOMBIA = timezone(timedelta(hours=-5))

# Clave del advisory lock de la corrida diaria (constante arbitraria de 64 bits).
CLAVE_LOCK_CORRIDA = 0x4150494C45474131

_RADICADO = re.compile(r"\d{23}")
_ENVIO = re.compile(r"envi[oa] a otros? despachos?")
_MAX_DETALLE = 500


class CorridaEnCurso(Exception):
    """Otra corrida tiene el lock: esta no debe empezar."""


@dataclass
class ResumenCorrida:
    corrida_id: uuid.UUID
    revisados: int = 0
    por_resultado: dict[ResultadoRevision, int] = field(default_factory=dict)
    no_consultables: int = 0
    circuito_abierto: bool = False

    def _contar(self, resultado: ResultadoRevision) -> None:
        self.revisados += 1
        self.por_resultado[resultado] = self.por_resultado.get(resultado, 0) + 1


@contextmanager
def lock_de_corrida(engine: Engine) -> Iterator[None]:
    """Lock de corrida única. Lanza `CorridaEnCurso` si otra lo tiene."""
    # AUTOCOMMIT: sin esto la conexión queda «idle in transaction» toda la
    # corrida (puede durar horas a ~1 req/s).
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conexion:
        obtenido = conexion.execute(
            text("SELECT pg_try_advisory_lock(:clave)"), {"clave": CLAVE_LOCK_CORRIDA}
        ).scalar()
        if not obtenido:
            raise CorridaEnCurso()
        try:
            yield
        finally:
            conexion.execute(
                text("SELECT pg_advisory_unlock(:clave)"), {"clave": CLAVE_LOCK_CORRIDA}
            )


def a_utc(fecha: datetime | None) -> datetime | None:
    """Fecha sin zona = hora de Colombia; con zona, a UTC."""
    if fecha is None:
        return None
    if fecha.tzinfo is None:
        fecha = fecha.replace(tzinfo=ZONA_COLOMBIA)
    return fecha.astimezone(timezone.utc)


def es_envio_a_otro_despacho(tipo: str, anotacion: str | None) -> bool:
    """«ENVÍO A OTROS DESPACHOS» / «Envía a otro despacho» (spike P4, C.1)."""
    return _ENVIO.search(normalizar(f"{tipo} {anotacion or ''}")) is not None


def es_consultable(expediente: Expediente) -> bool:
    return (
        expediente.seguimiento == Seguimiento.AUTOMATICO
        and expediente.tipo_identificador == TipoIdentificador.RADICADO_UNIFICADO
        and _RADICADO.fullmatch(expediente.identificador) is not None
    )


# -- corrida ---------------------------------------------------------------------


def ejecutar_corrida(
    session_factory: Callable[[], Session],
    fuente: FuenteConsulta,
    *,
    engine: Engine,
    ahora: datetime | None = None,
    dias_quietud: int = DIAS_QUIETUD,
) -> ResumenCorrida:
    """Revisa todos los expedientes consultables, uno tras otro. `engine` es
    solo para el lock. Lanza `CorridaEnCurso` sin tocar nada si ya hay una."""
    ahora = a_utc(ahora or datetime.now(timezone.utc))
    with lock_de_corrida(engine):
        resumen = ResumenCorrida(corrida_id=uuid.uuid4())
        with session_factory() as db:
            candidatos = db.execute(
                select(Expediente).where(
                    Expediente.activo.is_(True),
                    Expediente.seguimiento == Seguimiento.AUTOMATICO,
                )
                .order_by(Expediente.creado_en, Expediente.id)
            ).scalars().all()
            consultables = [(e.organizacion_id, e.id) for e in candidatos if es_consultable(e)]
            resumen.no_consultables = len(candidatos) - len(consultables)
            db.rollback()
        if resumen.no_consultables:
            logger.warning(
                "revisor: %s expediente(s) automatico no consultables por la fuente",
                resumen.no_consultables,
            )

        for organizacion_id, expediente_id in consultables:
            resultado = revisar_expediente(
                session_factory,
                fuente,
                organizacion_id=organizacion_id,
                expediente_id=expediente_id,
                corrida_id=resumen.corrida_id,
                ahora=ahora,
                dias_quietud=dias_quietud,
            )
            resumen._contar(resultado)
        resumen.circuito_abierto = fuente.circuito_abierto
        return resumen


# -- un expediente ---------------------------------------------------------------


@dataclass
class _EstadoProceso:
    id: uuid.UUID
    id_externo: int
    ultima_actualizacion: datetime | None
    vistas: frozenset[int]
    ultima_tipo: str | None
    ultima_anotacion: str | None


@dataclass
class _Lectura:
    identificador: str
    activos: list[_EstadoProceso]
    conocidos: set[int]  # `id_externo` de todo proceso, activo o no
    hay_procesos: bool
    # Algún proceso ya se consultó con éxito alguna vez. Un proceso dado de alta
    # cuya primera consulta falló no cuenta: su historial seguiría siendo línea
    # base, no novedad.
    ya_cargado: bool


@dataclass
class _Plan:
    """Lo que la fase de red decidió; la fase de escritura solo lo aplica."""

    consultas: dict[int, ConsultaProceso] = field(default_factory=dict)  # por id_externo
    remitidos: set[int] = field(default_factory=set)
    nuevos: list[ProcesoEncontrado] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)
    no_encontrado: bool = False


def revisar_expediente(
    session_factory: Callable[[], Session],
    fuente: FuenteConsulta,
    *,
    organizacion_id: uuid.UUID,
    expediente_id: uuid.UUID,
    corrida_id: uuid.UUID,
    ahora: datetime,
    dias_quietud: int = DIAS_QUIETUD,
) -> ResultadoRevision:
    """Una unidad de trabajo. Nunca lanza: lo que no se pudo verificar queda
    como `no_verificado`."""
    try:
        if fuente.circuito_abierto:
            return _registrar_solo_revision(
                session_factory, fuente, organizacion_id, expediente_id, corrida_id,
                ResultadoRevision.NO_VERIFICADO,
                "circuito abierto: no se consultó la fuente",
            )
        lectura = _leer(session_factory, fuente, organizacion_id, expediente_id)
        plan = _consultar_fuente(fuente, lectura, expediente_id, ahora, dias_quietud)
        return _escribir(
            session_factory, fuente, organizacion_id, expediente_id, corrida_id,
            ahora, lectura, plan,
        )
    except Exception as error:  # noqa: BLE001 — un expediente no frena la corrida
        logger.exception("revisor: fallo inesperado en el expediente %s", expediente_id)
        try:
            return _registrar_solo_revision(
                session_factory, fuente, organizacion_id, expediente_id, corrida_id,
                ResultadoRevision.NO_VERIFICADO,
                f"error interno: {type(error).__name__}",
            )
        except Exception:  # noqa: BLE001
            logger.exception("revisor: ni la Revision de %s se pudo escribir", expediente_id)
            return ResultadoRevision.NO_VERIFICADO


def _leer(
    session_factory: Callable[[], Session],
    fuente: FuenteConsulta,
    organizacion_id: uuid.UUID,
    expediente_id: uuid.UUID,
) -> _Lectura:
    with session_factory() as db:
        expediente = db.execute(
            select(Expediente).where(
                Expediente.id == expediente_id,
                Expediente.organizacion_id == organizacion_id,
            )
        ).scalar_one()
        procesos = db.execute(
            select(ProcesoFuente).where(
                ProcesoFuente.organizacion_id == organizacion_id,
                ProcesoFuente.expediente_id == expediente_id,
                ProcesoFuente.fuente == fuente.fuente,
            )
        ).scalars().all()
        activos = []
        for p in procesos:
            if p.estado != EstadoProcesoFuente.ACTIVO:
                continue
            vistas = frozenset(
                db.execute(
                    select(Actuacion.id_externo).where(
                        Actuacion.organizacion_id == organizacion_id,
                        Actuacion.proceso_fuente_id == p.id,
                    )
                ).scalars()
            )
            ultima = db.execute(
                select(Actuacion.tipo, Actuacion.anotacion)
                .where(
                    Actuacion.organizacion_id == organizacion_id,
                    Actuacion.proceso_fuente_id == p.id,
                )
                .order_by(Actuacion.consecutivo.desc())
                .limit(1)
            ).first()
            activos.append(
                _EstadoProceso(
                    id=p.id,
                    id_externo=p.id_externo,
                    ultima_actualizacion=a_utc(p.ultima_actualizacion_fuente),
                    vistas=vistas,
                    ultima_tipo=ultima.tipo if ultima else None,
                    ultima_anotacion=ultima.anotacion if ultima else None,
                )
            )
        lectura = _Lectura(
            identificador=expediente.identificador,
            activos=activos,
            conocidos={p.id_externo for p in procesos},
            hay_procesos=bool(procesos),
            ya_cargado=any(p.fecha_ultima_consulta is not None for p in procesos),
        )
        db.rollback()  # solo lectura: sin transacción abierta durante la red
        return lectura


def _consultar_fuente(
    fuente: FuenteConsulta,
    lectura: _Lectura,
    expediente_id: uuid.UUID,
    ahora: datetime,
    dias_quietud: int,
) -> _Plan:
    plan = _Plan()

    for p in lectura.activos:
        try:
            plan.consultas[p.id_externo] = _normalizar_consulta(
                fuente.consultar(
                    p.id_externo, EstadoVisto(p.ultima_actualizacion, p.vistas)
                )
            )
        except ErrorFuente as e:
            plan.errores.append(f"{p.id_externo}: {e}")

    # «Envío a otro despacho» en la última actuación: ese proceso terminó aquí
    # y continúa bajo otro idProceso.
    for p in lectura.activos:
        consulta = plan.consultas.get(p.id_externo)
        if consulta is None:
            continue
        if consulta.actuaciones_nuevas:
            ultima = consulta.actuaciones_nuevas[0]
            tipo, anotacion = ultima.tipo, ultima.anotacion
        else:
            tipo, anotacion = p.ultima_tipo, p.ultima_anotacion
        if tipo is not None and es_envio_a_otro_despacho(tipo, anotacion):
            plan.remitidos.add(p.id_externo)

    activos_restantes = [p for p in lectura.activos if p.id_externo not in plan.remitidos]
    if not _debe_resolver(
        lectura, activos_restantes, plan, expediente_id, ahora, dias_quietud
    ):
        return plan

    try:
        encontrados = fuente.resolver(lectura.identificador)
    except ErrorFuente as e:
        plan.errores.append(f"resolver: {e}")
        return plan

    if not encontrados and not lectura.hay_procesos:
        plan.no_encontrado = True
        return plan

    for encontrado in encontrados:
        if encontrado.id_externo in lectura.conocidos:
            continue
        plan.nuevos.append(encontrado)
        try:
            consulta = _normalizar_consulta(fuente.consultar(encontrado.id_externo, None))
        except ErrorFuente as e:
            # El proceso se da de alta igual; mañana se consulta de cero.
            plan.errores.append(f"{encontrado.id_externo}: {e}")
            continue
        plan.consultas[encontrado.id_externo] = consulta
        if consulta.actuaciones_nuevas:
            ultima = consulta.actuaciones_nuevas[0]
            if es_envio_a_otro_despacho(ultima.tipo, ultima.anotacion):
                # Ya nace remitido: no se queda «activo» hasta mañana.
                plan.remitidos.add(encontrado.id_externo)
    return plan


def _debe_resolver(
    lectura: _Lectura,
    activos_restantes: list[_EstadoProceso],
    plan: _Plan,
    expediente_id: uuid.UUID,
    ahora: datetime,
    dias_quietud: int,
) -> bool:
    if not activos_restantes:  # nunca encontrado, o todos remitidos
        return True
    if plan.remitidos:
        return True
    ultimas = []
    for p in activos_restantes:
        consulta = plan.consultas.get(p.id_externo)
        ultimas.append(
            (consulta.ultima_actualizacion if consulta else None) or p.ultima_actualizacion
        )
    if any(u is None for u in ultimas):
        return False
    if ahora - max(ultimas) < timedelta(days=dias_quietud):
        return False
    return (ahora.date().toordinal() + expediente_id.int) % dias_quietud == 0


def _normalizar_consulta(c: ConsultaProceso) -> ConsultaProceso:
    return ConsultaProceso(
        resultado=c.resultado,
        ultima_actualizacion=a_utc(c.ultima_actualizacion),
        actuaciones_nuevas=c.actuaciones_nuevas,
    )


def _escribir(
    session_factory: Callable[[], Session],
    fuente: FuenteConsulta,
    organizacion_id: uuid.UUID,
    expediente_id: uuid.UUID,
    corrida_id: uuid.UUID,
    ahora: datetime,
    lectura: _Lectura,
    plan: _Plan,
) -> ResultadoRevision:
    actuaciones_por_proceso = {
        id_externo: c.actuaciones_nuevas
        for id_externo, c in plan.consultas.items()
        if c.actuaciones_nuevas
    }
    total_nuevas = sum(len(a) for a in actuaciones_por_proceso.values())
    linea_base = not lectura.ya_cargado
    hay_novedad = total_nuevas > 0 and not linea_base

    detalles: list[str] = []
    if linea_base and total_nuevas:
        detalles.append(f"línea base: {total_nuevas} actuaciones cargadas")
    if plan.remitidos:
        detalles.append("remitido a otro despacho")
    if plan.errores:
        detalles.append("no verificado: " + "; ".join(plan.errores))

    # Sin ningún proceso activo (todos remitidos y el destino aún sin resolver)
    # nadie está mirando el expediente: decir `sin_novedad` sería tranquilidad
    # falsa. Una novedad de este mismo día (la propia remisión) sí se reporta.
    activos_finales = [
        p.id_externo
        for p in [*lectura.activos, *plan.nuevos]
        if p.id_externo not in plan.remitidos
    ]
    sin_proceso_activo = (
        not activos_finales and bool(lectura.conocidos or plan.nuevos)
    )
    if sin_proceso_activo:
        detalles.append("sin proceso activo: destino de la remisión sin resolver")

    if hay_novedad:
        resultado = ResultadoRevision.CON_NOVEDAD
    elif plan.errores or sin_proceso_activo:
        resultado = ResultadoRevision.NO_VERIFICADO
    elif plan.no_encontrado:
        resultado = ResultadoRevision.NO_ENCONTRADO
    else:
        resultado = ResultadoRevision.SIN_NOVEDAD

    with session_factory() as db:
        revision = Revision(
            organizacion_id=organizacion_id,
            expediente_id=expediente_id,
            fuente=fuente.fuente,
            resultado=resultado,
            corrida_id=corrida_id,
            detalle="; ".join(detalles)[:_MAX_DETALLE] or None,
        )
        db.add(revision)
        db.flush()

        procesos = {
            p.id_externo: p
            for p in db.execute(
                select(ProcesoFuente).where(
                    ProcesoFuente.organizacion_id == organizacion_id,
                    ProcesoFuente.expediente_id == expediente_id,
                    ProcesoFuente.fuente == fuente.fuente,
                )
            ).scalars()
        }
        for encontrado in plan.nuevos:
            p = ProcesoFuente(
                organizacion_id=organizacion_id,
                expediente_id=expediente_id,
                fuente=fuente.fuente,
                id_externo=encontrado.id_externo,
                id_conexion=encontrado.id_conexion,
                despacho=encontrado.despacho,
                departamento=encontrado.departamento,
                es_privado=encontrado.es_privado,
                estado=EstadoProcesoFuente.ACTIVO,
            )
            db.add(p)
            procesos[encontrado.id_externo] = p
        db.flush()

        for id_externo, consulta in plan.consultas.items():
            p = procesos[id_externo]
            if consulta.ultima_actualizacion is not None:
                p.ultima_actualizacion_fuente = consulta.ultima_actualizacion
            p.fecha_ultima_consulta = ahora
            for a in consulta.actuaciones_nuevas:
                db.add(_a_modelo(a, p, revision))
        for id_externo in plan.remitidos:
            procesos[id_externo].estado = EstadoProcesoFuente.REMITIDO
        db.commit()
    return resultado


def _a_modelo(
    a: ActuacionNormalizada, proceso: ProcesoFuente, revision: Revision
) -> Actuacion:
    return Actuacion(
        organizacion_id=proceso.organizacion_id,
        proceso_fuente_id=proceso.id,
        revision_id=revision.id,
        id_externo=a.id_externo,
        consecutivo=a.consecutivo,
        fecha_actuacion=a_utc(a.fecha_actuacion),
        tipo=a.tipo,
        anotacion=a.anotacion,
        fecha_inicial=a_utc(a.fecha_inicial),
        fecha_final=a_utc(a.fecha_final),
        fecha_registro=a_utc(a.fecha_registro),
        con_documentos=a.con_documentos,
        crudo=a.crudo,
    )


def _registrar_solo_revision(
    session_factory: Callable[[], Session],
    fuente: FuenteConsulta,
    organizacion_id: uuid.UUID,
    expediente_id: uuid.UUID,
    corrida_id: uuid.UUID,
    resultado: ResultadoRevision,
    detalle: str,
) -> ResultadoRevision:
    with session_factory() as db:
        db.rollback()  # una sesión que vino de un fallo puede traer estado sucio
        db.add(
            Revision(
                organizacion_id=organizacion_id,
                expediente_id=expediente_id,
                fuente=fuente.fuente,
                resultado=resultado,
                corrida_id=corrida_id,
                detalle=detalle[:_MAX_DETALLE],
            )
        )
        db.commit()
    return resultado
