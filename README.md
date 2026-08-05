# API Legal

Plataforma para usuarios individuales y firmas pequeñas del ámbito legal, construida sobre una API
pensada desde el día 1 con el rigor de un producto público. Nace del proceso manual de revisión de
expedientes judiciales que describe Juan Diego Infante Muñoz — ver la bóveda de Obsidian del
proyecto para el porqué completo.

> **Bus factor = 1.** Este README debe bastar para que otro desarrollador clone, levante y entienda
> el proyecto sin preguntarle nada a Martin. Si algo no alcanza, es un defecto del README: repórtalo.

## Qué es esto (y qué no es todavía)

Esto es el esqueleto de la Fase 0 (ver `Proyecto API Legal.md` en la bóveda): repositorio, health
check, logging estructurado. **Todavía no incluye** base de datos, autenticación, ni el motor de
seguimiento de expedientes — eso es Fase 1, ya definida en la decisión
`Flujo central de Fase 1 — seguimiento de expedientes judiciales` (bóveda, `API Legal/Decisiones/`).

## Arrancar en local

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Confirmar que funciona:

```bash
curl http://127.0.0.1:8000/v1/health
```

Documentación OpenAPI autogenerada (contrato explícito desde el código) en
`http://127.0.0.1:8000/docs`.

## Pruebas

```bash
pytest
```

Cubren el camino feliz (`/v1/health` responde 200) y el error principal (ruta inexistente responde
404, no 500) — mínimo exigido por la Definition of Done del proyecto.

## Estructura

```
app/
  main.py          - punto de entrada; monta las rutas bajo /v1 y el logging de peticiones
  core/config.py   - configuración por variables de entorno (pydantic-settings)
  core/logging.py  - logging estructurado (JSON) a stdout
  api/v1/health.py - GET /v1/health
tests/             - pruebas automáticas
.github/workflows/ci.yml - pytest en cada push (inerte hasta conectar un remoto)
```

## Convenciones (no negociables)

Definidas en `Reglas de trabajo del desarrollador único` (bóveda de Obsidian, `Transversal/`):

- Toda ruta nueva va bajo `/v1`. El contrato OpenAPI se genera desde el código, no se escribe a mano.
- Multi-tenant desde el modelo de datos: cuando exista base de datos, **toda** tabla lleva
  identificador de organización, sin excepción.
- Audit log inmutable desde el primer endpoint que toque datos reales.
- Ninguna tarea se da por terminada sin: endpoint bajo `/v1` + contrato OpenAPI actualizado + prueba
  del camino feliz y del error principal + evento en el audit log (cuando aplique) + desplegado.
- Antes de ampliar alcance, contrastar con el "fuera de alcance" de `00 · Tesis y Alcance` (Notion).

## Pendiente (siguiente sesión de código, Semana 2 del horario)

- Cuentas y accesos: dominio, hosting, base de datos, gestor de secretos — decisión de Martin, no
  del agente.
- Desplegar este esqueleto a producción (hoy solo corre en local).
- Modelo de datos base (organización, auditoría) y autenticación.

## Nota sobre esta carpeta

Vive dentro de `Revision de procesos`, sincronizada con OneDrive, junto a los documentos fuente
originales (Word y Excel) — es la misma carpeta que ya usaba Martin, a propósito. Conviene que
Windows/OneDrive no sincronice `.venv/` ni `__pycache__/`: ya están en `.gitignore`, y si OneDrive
insiste en subirlos igual, excluirlos desde "Liberar espacio" / propiedades de la carpeta.

## Dónde está el porqué

La bóveda de Obsidian (`Proyectos/API Legal/`) tiene el contexto que este README no repite: la
tesis del proyecto, las decisiones tomadas y por qué, el estado real de cada fase. Este repositorio
es el cómo; la bóveda es el porqué.
