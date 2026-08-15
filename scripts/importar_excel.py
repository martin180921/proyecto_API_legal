"""Importa el inventario de expedientes del Excel de control manual de Juan
Diego a una organización ya existente (Etapa Entrada, S3-4).

Por qué es "conservador"
-------------------------
La hoja `identificación procesos` **no es una tabla**: es texto puesto en
celdas sin columnas fijas, con el radicado bajo etiquetas distintas según la
fila (`Ref.`, `Referencia`, `Expediente`, `Radicación No.`...). Además, al
inspeccionarla se encontraron radicados guardados como número de coma
flotante (`8.51624089002202e+22`): un `float64` no representa 23 dígitos
exactos, así que esa pérdida de precisión ya ocurrió dentro del propio
archivo — no hay forma de reconstruirla desde aquí, y este script no lo
intenta.

Por eso el importador no adivina estructura: agrupa filas en bloques
separados por filas en blanco y, de cada bloque, solo usa lo que puede
identificar con confianza:
- **radicado**: una tanda de exactamente 23 dígitos seguidos, tras quitar
  espacios/guiones/puntos de la celda. Si un bloque trae más de un radicado
  distinto, o el único candidato viene de un número ya corrompido por Excel,
  **no se importa** — se reporta con el motivo, nunca se arriesga a inventar
  cuál es el bueno.
- **tipo_proceso**: heredado de la última cabecera de sección vista al bajar
  por la hoja (`procesos civiles`, `PROCESOS ADMINISTRATIVOS`). Los bloques
  bajo `CONTRALORIA` se descartan sin más: fuera del alcance de F1
  ([[Flujo central de Fase 1 — seguimiento de expedientes judiciales]]).
- **juzgado**: primera celda que empieza por `JUZGADO`/`JUEZ`/`TRIBUNAL`.
- **partes**: todas las celdas que empiezan por `DEMANDANTE`/`DEMANDADO`/
  `DDO`/`ACREEDOR`/`DEUDOR`, unidas con salto de línea.
- **ultima_actuacion_conocida**: celda que empieza por `ASUNTO`, si la hay.
- **despacho**: la hoja no distingue despacho de juzgado de forma fiable, así
  que este campo queda sin poblar desde el Excel a propósito.

Cualquier bloque sin radicado limpio, con radicado ambiguo, con precisión ya
perdida, o de una sección que no sea civil/administrativo, se salta y queda
en el reporte final con el motivo — es justo lo que pide la parada P3:
"filas que no importan y por qué".

Modo simulación por defecto
----------------------------
Sin `--aplicar`, el script solo imprime el reporte (qué importaría, qué
saltaría y por qué) y no escribe nada. Pensado para revisar antes de
comprometerse, dado lo irregular de la fuente.

Uso
---
    python scripts/importar_excel.py --organizacion bufete-infante \
        --archivo "C:\\ruta\\a\\procesos activos .xlsx"

    python scripts/importar_excel.py --organizacion bufete-infante \
        --archivo "C:\\ruta\\a\\procesos activos .xlsx" --aplicar
"""
import argparse
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

# `python scripts/importar_excel.py` pone `scripts/` en sys.path, no la raíz
# del repositorio — mismo motivo que en `scripts/crear_organizacion.py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import openpyxl  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.models.expediente import Expediente, TipoProceso  # noqa: E402
from app.models.organizacion import Organizacion  # noqa: E402
from app.services import auditoria  # noqa: E402

ORIGEN = "scripts/importar_excel.py"

_CARACTERES_A_QUITAR = re.compile(r"[\s\-\.\u00a0]")
_LONGITUD_RADICADO = 23

_PREFIJOS_JUZGADO = ("JUZGADO", "JUEZ", "TRIBUNAL")
_PREFIJOS_PARTE = ("DEMANDANTE", "DEMANDADO", "DDO", "ACREEDOR", "DEUDOR")
_PREFIJOS_ACTUACION = ("ASUNTO",)

_SECCION_FUERA_DE_ALCANCE = "CONTRALORIA"
_SECCIONES_TIPO_PROCESO = {
    "PROCESOS CIVILES": TipoProceso.CIVIL,
    "PROCESO CIVIL": TipoProceso.CIVIL,
    "PROCESOS ADMINISTRATIVOS": TipoProceso.ADMINISTRATIVO,
    "PROCESO ADMINISTRATIVO": TipoProceso.ADMINISTRATIVO,
}

# Umbral para tratar un número de celda como "posible radicado que Excel
# convirtió a float": por debajo de esto es cualquier otro dato numérico
# (fechas serializadas, cantidades), no un radicado.
_DIGITOS_MINIMOS_SOSPECHA_NUMERICA = 20


def _normalizar(texto: str) -> str:
    """Mayúsculas, sin tildes ni NBSP — para comparar contra prefijos fijos."""
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return sin_tildes.upper().replace("\xa0", " ").strip()


def _candidatos_radicado(texto: str) -> list[str]:
    """Tandas de exactamente 23 dígitos seguidos tras limpiar separadores.

    Busca dentro del texto en vez de exigir que la celda entera sea el
    radicado, porque en esta hoja el radicado a veces viene pegado a más
    texto en la misma celda (`"...000310. TRIBUNAL..."`). No recorta ni
    completa nada: si la tanda de dígitos no mide exactamente 23, no cuenta.
    """
    limpio = _CARACTERES_A_QUITAR.sub("", texto)
    return [grupo for grupo in re.findall(r"\d+", limpio) if len(grupo) == _LONGITUD_RADICADO]


def _detectar_seccion(texto_normalizado: str):
    """Solo cuenta como cabecera de sección si la celda **es** la etiqueta,
    no si la contiene de paso. Con `in` en vez de `==`, una fila como
    `"Demandado: CONTRALORIA GENERAL DE LA REPÚBLICA"` (un caso
    administrativo cuya contraparte es la Contraloría, no un caso *de*
    responsabilidad fiscal) se confundía con la cabecera de la sección
    `CONTRALORIA` y sacaba de alcance todo lo que venía después."""
    if texto_normalizado == _SECCION_FUERA_DE_ALCANCE:
        return _SECCION_FUERA_DE_ALCANCE
    for etiqueta, tipo in _SECCIONES_TIPO_PROCESO.items():
        if texto_normalizado == etiqueta:
            return tipo
    return None


@dataclass
class Bloque:
    fila_inicio: int
    seccion: object = None  # TipoProceso | "CONTRALORIA" | None
    radicado: str | None = None
    radicado_ambiguo: bool = False
    radicado_precision_perdida: bool = False
    juzgado: str | None = None
    partes: list[str] = field(default_factory=list)
    ultima_actuacion_conocida: str | None = None
    extracto: str = ""  # primeros caracteres vistos, para el reporte


def leer_bloques(ws) -> list[Bloque]:
    """Agrupa filas en bloques separados por filas en blanco.

    Una cabecera de sección (`procesos civiles`, `CONTRALORIA`...) actualiza
    la sección vigente y cierra el bloque en curso: no se asume que comparte
    fila en blanco con lo que viene después.
    """
    bloques: list[Bloque] = []
    actual: Bloque | None = None
    seccion_actual = None

    def _abrir_bloque(indice_fila: int) -> Bloque:
        nuevo = Bloque(fila_inicio=indice_fila, seccion=seccion_actual)
        bloques.append(nuevo)
        return nuevo

    for indice_fila, fila in enumerate(ws.iter_rows(values_only=True), start=1):
        valores = [c for c in fila if c is not None and str(c).strip() != ""]
        if not valores:
            actual = None
            continue

        for celda in fila:
            if celda is None:
                continue

            if isinstance(celda, (int, float)) and not isinstance(celda, bool):
                if len(str(int(celda))) >= _DIGITOS_MINIMOS_SOSPECHA_NUMERICA:
                    if actual is None:
                        actual = _abrir_bloque(indice_fila)
                    actual.radicado_precision_perdida = True
                continue

            texto = str(celda).strip()
            if not texto:
                continue
            normalizado = _normalizar(texto)

            deteccion = _detectar_seccion(normalizado)
            if deteccion is not None:
                seccion_actual = deteccion
                actual = None
                continue

            if actual is None:
                actual = _abrir_bloque(indice_fila)
            if not actual.extracto:
                actual.extracto = texto[:60]

            for candidato in _candidatos_radicado(texto):
                if actual.radicado is None:
                    actual.radicado = candidato
                elif candidato != actual.radicado:
                    actual.radicado_ambiguo = True

            if normalizado.startswith(_PREFIJOS_JUZGADO) and actual.juzgado is None:
                actual.juzgado = texto
            elif normalizado.startswith(_PREFIJOS_PARTE):
                actual.partes.append(texto)
            elif normalizado.startswith(_PREFIJOS_ACTUACION) and actual.ultima_actuacion_conocida is None:
                actual.ultima_actuacion_conocida = texto

    return bloques


@dataclass
class Resultado:
    fila_inicio: int
    radicado: str | None
    motivo_salto: str | None  # None si se importó (o importaría, en simulación)


def clasificar(bloques: list[Bloque], radicados_ya_vistos: set[str]) -> tuple[list[Bloque], list[Resultado]]:
    """Separa los bloques importables de los que se saltan, con motivo."""
    importables: list[Bloque] = []
    resultados: list[Resultado] = []

    for bloque in bloques:
        motivo = None
        if bloque.seccion == _SECCION_FUERA_DE_ALCANCE:
            motivo = "fuera_de_alcance_contraloria"
        elif bloque.seccion not in (TipoProceso.CIVIL, TipoProceso.ADMINISTRATIVO):
            motivo = "sin_tipo_proceso_identificado"
        elif bloque.radicado_ambiguo:
            motivo = "radicado_ambiguo"
        elif bloque.radicado is None and bloque.radicado_precision_perdida:
            motivo = "radicado_guardado_como_numero_precision_perdida"
        elif bloque.radicado is None:
            motivo = "radicado_no_encontrado"
        elif bloque.radicado in radicados_ya_vistos:
            motivo = "radicado_duplicado_en_el_mismo_archivo"
        else:
            radicados_ya_vistos.add(bloque.radicado)
            importables.append(bloque)

        resultados.append(Resultado(fila_inicio=bloque.fila_inicio, radicado=bloque.radicado, motivo_salto=motivo))

    return importables, resultados


def _partes_texto(bloque: Bloque) -> str | None:
    return "\n".join(bloque.partes) if bloque.partes else None


def main() -> int:
    # La consola de Windows no siempre usa un codepage que soporte tildes o
    # comillas tipográficas (cp1252 sí, el cmd.exe por defecto con OEM 850 a
    # veces no): sin esto, un `print` con esos caracteres tumba el script a
    # medio reporte en vez de solo perder el acento.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--organizacion", required=True, help="Slug de la organización destino")
    parser.add_argument("--archivo", required=True, help="Ruta al .xlsx de inventario")
    parser.add_argument("--hoja", default=None, help="Nombre de la hoja (por defecto: la primera)")
    parser.add_argument(
        "--aplicar",
        action="store_true",
        help="Escribe de verdad. Sin esta opción el script solo reporta (simulación).",
    )
    args = parser.parse_args()

    wb = openpyxl.load_workbook(args.archivo, data_only=True)
    hoja = wb[args.hoja] if args.hoja else wb[wb.sheetnames[0]]
    bloques = leer_bloques(hoja)

    engine = create_engine(settings.database_url)
    with Session(engine) as db:
        organizacion = db.query(Organizacion).filter_by(slug=args.organizacion).one_or_none()
        if organizacion is None:
            sys.exit(f"No existe ninguna organización con el slug «{args.organizacion}». No se ha hecho nada.")

        radicados_existentes = {
            radicado
            for (radicado,) in db.query(Expediente.radicado).filter_by(organizacion_id=organizacion.id).all()
        }
        radicados_vistos = set(radicados_existentes)
        importables, resultados = clasificar(bloques, radicados_vistos)

        # Los que ya existen en la organización se detectan aparte: no son un
        # defecto del Excel, son expedientes que ya están en la base.
        finales: list[Bloque] = []
        for bloque in importables:
            if bloque.radicado in radicados_existentes:
                for resultado in resultados:
                    if resultado.fila_inicio == bloque.fila_inicio:
                        resultado.motivo_salto = "radicado_ya_existe_en_la_organizacion"
                        break
            else:
                finales.append(bloque)

        creados = 0
        if args.aplicar:
            for bloque in finales:
                expediente = Expediente(
                    organizacion_id=organizacion.id,
                    radicado=bloque.radicado,
                    juzgado=bloque.juzgado,
                    despacho=None,
                    partes=_partes_texto(bloque),
                    tipo_proceso=bloque.seccion,
                    ultima_actuacion_conocida=bloque.ultima_actuacion_conocida,
                )
                db.add(expediente)
                try:
                    db.flush()
                except IntegrityError:
                    db.rollback()
                    for resultado in resultados:
                        if resultado.fila_inicio == bloque.fila_inicio:
                            resultado.motivo_salto = "radicado_duplicado_en_la_organizacion"
                            break
                    continue

                auditoria.registrar(
                    db,
                    organizacion_id=organizacion.id,
                    accion="crear",
                    entidad="expediente",
                    entidad_id=expediente.id,
                    detalle={"origen": ORIGEN, "fila_excel": bloque.fila_inicio},
                )
                creados += 1
            db.commit()

        # --- Reporte -----------------------------------------------------
        motivos: dict[str, int] = {}
        for resultado in resultados:
            if resultado.motivo_salto:
                motivos[resultado.motivo_salto] = motivos.get(resultado.motivo_salto, 0) + 1

        print(f"Hoja leída: «{hoja.title}» — {len(bloques)} bloques detectados.")
        print(f"Organización destino: {organizacion.nombre} ({organizacion.slug})")
        print(f"Importables: {len(finales)}" + (f" — creados: {creados}" if args.aplicar else " (simulación, nada escrito)"))
        print(f"Saltados: {sum(motivos.values())}")
        for motivo, cantidad in sorted(motivos.items(), key=lambda item: -item[1]):
            print(f"  {motivo}: {cantidad}")

        print("\nDetalle por fila:")
        for resultado in resultados:
            estado = resultado.motivo_salto or ("creado" if args.aplicar else "importable")
            print(f"  fila {resultado.fila_inicio}: radicado={resultado.radicado or '(ninguno)'} -> {estado}")

        if not args.aplicar:
            print("\nModo simulación: no se ha escrito nada. Repite con --aplicar para confirmar.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
