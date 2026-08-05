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

## Producción

`https://proyectoapilegal-production.up.railway.app` — Railway. Despliegue automático: cada push a
`main` dispara un deploy nuevo, sin paso manual.

```bash
curl https://proyectoapilegal-production.up.railway.app/v1/health
```

## Base de datos local

Postgres en Docker. No hay contenedor de la aplicación a propósito: la app se corre con `uvicorn`
en la máquina, que es más rápido de iterar.

```bash
docker compose up -d db
```

Eso levanta Postgres 16 y, la primera vez, crea el rol `api_legal_app` y las bases `api_legal`
(desarrollo) y `api_legal_test` (pruebas) — ver `scripts/init-db.sql`. Después, aplicar las
migraciones:

```bash
alembic upgrade head
```

> **El rol `api_legal_app` no es superusuario, y eso es deliberado.** Un superusuario de Postgres
> ignora los `GRANT`/`REVOKE`, así que con uno el `REVOKE UPDATE, DELETE` que protege el audit log
> no haría nada y la prueba que lo verifica pasaría en verde sin comprobar nada. Verificado contra
> Postgres 16 el 2026-08-05.

Si cambias `scripts/init-db.sql`, hace falta `docker compose down -v` para que vuelva a ejecutarse:
solo corre al crear el volumen.

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

Necesitan la base de datos levantada (`docker compose up -d db`).

```bash
pytest
```

**Corren contra Postgres, no SQLite.** Motivo: en la revisión de la parada P1 (2026-08-05) SQLite
dio un falso verde — no validaba las claves foráneas, así que una fila huérfana pasaba en verde y
habría reventado en producción. Además el `REVOKE` del audit log es DDL de Postgres, así que sobre
SQLite las migraciones ni siquiera podían ejecutarse y no se probaban en ningún sitio.

El esquema de pruebas lo crea `alembic upgrade head`, no `create_all`: cada ejecución de la suite
comprueba también que las migraciones corren y dicen lo mismo que los modelos. Cada test va dentro
de una transacción que se revierte al terminar.

La suite cubre el camino feliz (`/v1/health` responde 200) y el error principal (ruta inexistente
responde 404, no 500) — mínimo exigido por la Definition of Done —, más el modelo de datos, la
integridad referencial, la unicidad del email por organización y la inmutabilidad del audit log.

Para apuntar a otra base de datos, `DATABASE_URL_TEST`. La suite se niega a arrancar si esa
variable parece apuntar a producción.

## Estructura

```
app/
  main.py          - punto de entrada; monta las rutas bajo /v1 y el logging de peticiones
  core/config.py   - configuración por variables de entorno (pydantic-settings)
  core/db.py       - engine, sesiones y declarative base
  core/logging.py  - logging estructurado (JSON) a stdout
  api/v1/health.py - GET /v1/health
  models/          - modelos SQLAlchemy (organizacion, usuario, evento_auditoria)
  services/        - lógica de escritura; auditoria.py es la única vía al audit log
alembic/versions/  - migraciones
tests/             - pruebas automáticas (contra Postgres)
scripts/init-db.sql      - rol y bases de datos de desarrollo
docker-compose.yml       - Postgres local
.github/workflows/ci.yml - pytest contra Postgres en cada push
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

- Modelo de datos base (organización, auditoría) y autenticación (T2–T4 de `Plan técnico por
  fases.md` en la bóveda).

## Nota sobre esta carpeta

Este repositorio vive en `C:\dev\proyecto_API_legal`, **fuera de** OneDrive (a propósito: git y
OneDrive no se llevan bien). Los documentos fuente originales de Juan Diego (Word y Excel) siguen en
`Desktop\Revision de procesos`, sincronizada con OneDrive — esa carpeta ya no tiene código.

## Dónde está el porqué

La bóveda de Obsidian (`Proyectos/API Legal/`) tiene el contexto que este README no repite: la
tesis del proyecto, las decisiones tomadas y por qué, el estado real de cada fase. Este repositorio
es el cómo; la bóveda es el porqué.
