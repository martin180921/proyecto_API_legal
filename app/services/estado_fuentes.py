"""Lectura del estado del motor de revisión para `GET /v1/estado-fuentes`.
Solo lee `revisiones` (de solo añadir): ninguna mutación, ningún evento de
auditoría. Todo filtrado por `organizacion_id`."""
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.expediente import Expediente
from app.models.revision import ResultadoRevision, Revision
from app.schemas.estado_fuentes import (
    ConteoResultados,
    CorridaResumen,
    EstadoFuentesResponse,
    ExpedienteNoVerificado,
)


def obtener(
    db: Session, organizacion_id: uuid.UUID, limit: int, offset: int
) -> EstadoFuentesResponse:
    # La última corrida de ESTA organización: la revisión más reciente que
    # pertenezca a una corrida del job (las hechas a mano no llevan id).
    corrida_id = db.scalar(
        select(Revision.corrida_id)
        .where(Revision.organizacion_id == organizacion_id, Revision.corrida_id.is_not(None))
        .order_by(Revision.revisado_en.desc(), Revision.id)
        .limit(1)
    )
    if corrida_id is None:
        return EstadoFuentesResponse(
            ultima_corrida=None, no_verificados=[], no_verificados_total=0, limit=limit, offset=offset
        )

    de_la_corrida = (Revision.organizacion_id == organizacion_id, Revision.corrida_id == corrida_id)

    filas = db.execute(
        select(Revision.resultado, func.count()).where(*de_la_corrida).group_by(Revision.resultado)
    ).all()
    conteo = {resultado.value: n for resultado, n in filas}
    inicio, fin = db.execute(
        select(func.min(Revision.revisado_en), func.max(Revision.revisado_en)).where(*de_la_corrida)
    ).one()

    no_verificados = db.execute(
        select(Revision, Expediente.identificador)
        .join(
            Expediente,
            (Expediente.organizacion_id == Revision.organizacion_id)
            & (Expediente.id == Revision.expediente_id),
        )
        .where(*de_la_corrida, Revision.resultado == ResultadoRevision.NO_VERIFICADO)
        .order_by(Revision.revisado_en, Revision.id)
        .limit(limit)
        .offset(offset)
    ).all()

    return EstadoFuentesResponse(
        ultima_corrida=CorridaResumen(
            corrida_id=corrida_id,
            iniciada_en=inicio,
            ultima_revision_en=fin,
            total=sum(conteo.values()),
            resultados=ConteoResultados(**conteo),
        ),
        no_verificados=[
            ExpedienteNoVerificado(
                expediente_id=r.expediente_id,
                identificador=identificador,
                fuente=r.fuente,
                detalle=r.detalle,
                revisado_en=r.revisado_en,
            )
            for r, identificador in no_verificados
        ],
        no_verificados_total=conteo.get(ResultadoRevision.NO_VERIFICADO.value, 0),
        limit=limit,
        offset=offset,
    )
