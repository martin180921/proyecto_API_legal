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

La configuración de despliegue vive en `railway.json`, versionada, no en la UI de Railway. Lo
importante de ese archivo es el **pre-deploy command**: `alembic upgrade head` corre antes de
arrancar el contenedor. Sin él, con despliegue automático desde `main`, el código se adelanta al
esquema de la base de datos y es cuestión de tiempo que rompa.

Railway necesita, además, una base de datos Postgres en el proyecto y la variable `DATABASE_URL`
del servicio de la API referenciando la del Postgres (`${{Postgres.DATABASE_URL}}`).

> **`SECRET_KEY` real antes del primer deploy con T4.** El JWT de sesión se firma con esta clave; el
> valor por defecto de `config.py` es `cambiar-en-produccion`, está en este repo público y no sirve.
> Generarla con `python -c "import secrets; print(secrets.token_urlsafe(64))"` y ponerla como
> variable de entorno en el servicio de Railway — nunca en el repo ni en la bóveda.
>
> **No hay que acordarse: el código lo impide.** Con `APP_ENV=production`, `config.py` se niega a
> construir la configuración si la clave es una de las de ejemplo o mide menos de 32 caracteres.
> La app no arranca, el pre-deploy falla y el deploy no sale. Es a propósito: sin esta guarda el
> fallo sería silencioso (la app arranca, `/v1/health` responde 200) y cualquiera que leyera el
> repo podría firmar un JWT válido para cualquier organización.

> **El audit log no está protegido si el rol de la base de datos es superusuario.** Railway entrega
> por defecto un `DATABASE_URL` con superusuario, y un superusuario de Postgres ignora el `REVOKE`
> que protege `eventos_auditoria`. Comprobar cuál es el caso:
>
> ```sql
> select current_user, usesuper from pg_user where usename = current_user;
> ```
>
> Si devuelve `t`, la barrera es inerte en producción. Está aceptado para el piloto y planificado
> para F3 (rol de migración ≠ rol de aplicación, ninguno superusuario) — pero conviene saberlo, no
> descubrirlo.

## Base de datos local

Postgres en Docker. No hay contenedor de la aplicación a propósito: la app se corre con `uvicorn`
en la máquina, que es más rápido de iterar.

```bash
docker compose up -d db
```

Eso levanta Postgres 18 y, la primera vez, crea el rol `api_legal_app` y las bases `api_legal`
(desarrollo) y `api_legal_test` (pruebas) — ver `scripts/init-db.sql`. Después, aplicar las
migraciones:

```bash
alembic upgrade head
```

> **La major está clavada a la de Railway (18).** No es cosmético: un dump de 18 no restaura en 16,
> y las diferencias entre majors aparecen justo donde más duelen (permisos, tipos, planificador).
> Si Railway sube de major, este repo sube con él.

> **El rol `api_legal_app` no es superusuario, y eso es deliberado.** Un superusuario de Postgres
> ignora los `GRANT`/`REVOKE`, así que con uno el `REVOKE UPDATE, DELETE` que protege el audit log
> no haría nada y la prueba que lo verifica pasaría en verde sin comprobar nada. Verificado contra
> Postgres 16 el 2026-08-05.

Si cambias `scripts/init-db.sql`, hace falta `docker compose down -v` para que vuelva a ejecutarse:
solo corre al crear el volumen.

### Datos de desarrollo

```bash
python scripts/seed_local.py
```

Datos **sintéticos**, nunca una copia de producción — decidido el 2026-08-05, ver la bóveda
(«Réplica local de Postgres sin datos de producción»). No es solo prudencia: los seeds están
elegidos para ejercitar las decisiones registradas (dos organizaciones para que un fallo de
aislamiento se note, el mismo email en ambas para fijar `uq_usuarios_organizacion_email`, un evento
de auditoría con `entidad_id` NULL). Una copia de producción no garantiza ninguno de esos casos.

El script se niega a correr contra cualquier cosa que no sea `localhost`, porque hace `DELETE`.

### Comprobar deriva contra Railway

```bash
export DATABASE_PUBLIC_URL='postgresql://...@...proxy.rlwy.net:PUERTO/railway'
python scripts/comparar-esquema.py
```

Compara el DDL de Railway con el que producen las migraciones en local y falla si difieren. Es lo
que detecta que alguien tocó producción a mano, que una migración quedó a medias, o que Railway se
quedó en una revisión anterior — fallos que si no aparecen aquí, aparecen el día del despliegue.

La URL entra por variable de entorno y nunca se escribe en un archivo del repo. Usa el `pg_dump` del
contenedor `postgres:18`, así que no hay que instalar cliente de Postgres en Windows.

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

## Autenticación (T4)

Sesión de usuario por JWT, con el hueco dejado para que en el futuro una API key resuelva el mismo
actor (`app/core/security.py`, `ActorActual` / `usuario_actual`) — la API key en sí no se construye
todavía. Parámetros fijados por Martin, no elegidos por el código: JWT **HS256**, expiración **8
horas sin refresh**, rate-limit de login con contador simple en memoria (`app/core/rate_limit.py`,
sin `slowapi`): **5 intentos por clave (usuario u origen) en 15 minutos**, con evento de auditoría
(`entidad="login_fallido"`) al superarlo.

- `POST /v1/auth/registro` — crea la organización (con un `slug` único generado del nombre) y su
  primer usuario. `201` con `organizacion_id`, `organizacion_slug`, `usuario_id`, `email`.
  **Cerrado por defecto**: devuelve `403` salvo que `REGISTRO_ABIERTO=true` (ver abajo).
- `POST /v1/auth/login` — recibe `organizacion` (el **slug**, no el nombre visible), `email` y
  `contrasena`. `200` con el token; `401` si las credenciales no coinciden; `429` si se supera el
  rate-limit.
- `GET /v1/auth/yo` — con `Authorization: Bearer <token>`, devuelve el usuario autenticado.

El login identifica la organización por **slug**, no por `nombre`: `nombre` no tiene restricción de
unicidad (dos bufetes pueden llamarse igual, o cambiar de nombre), así que no sirve como clave de
login. Ver `app/models/organizacion.py` y la migración `91bd238ab035`.

**Límite conocido del rate-limit**: si el `slug` de la organización no existe, la petición se
rechaza con `401` sin dejar evento de auditoría ni contar contra el límite — `organizacion_id` es
`NOT NULL` en el audit log y no hay a qué organización atribuir el intento. Aceptado para el piloto,
mismo criterio que los demás riesgos residuales documentados en la bóveda.

### El registro está cerrado, y las altas se hacen por consola

`REGISTRO_ABIERTO=false` es el valor por defecto. Ese endpoint es público, sin sesión, y ejecuta
bcrypt, que es caro a propósito: abierto permite a cualquiera crear organizaciones ilimitadas en la
base del piloto, y unas pocas peticiones concurrentes bastan para tumbar el único proceso de uvicorn
que arranca `railway.json`. F0 no necesita autoservicio — el piloto es un abogado.

Con el registro cerrado, el alta se hace así:

```bash
python scripts/crear_organizacion.py --nombre "Bufete Infante" --slug bufete-infante --email juan.diego@example.com
```

La contraseña se pide por consola para que no quede en el historial del shell. El `slug` es
**explícito**, a diferencia del endpoint que lo deriva del nombre: es lo que se teclea en cada login,
así que se elige a conciencia. El script no borra nada y se para sin escribir si el slug ya existe.
Deja los mismos eventos de auditoría que el endpoint.

`/registro` tiene además rate-limit por IP (misma ventana que el login) tanto abierto como cerrado.

### Qué deja el login en el audit log

*Quién entró y cuándo* es el evento principal de una plataforma legal con un audit log de posible
valor probatorio, así que el login correcto deja rastro igual que el fallido.

| Qué pasa | `accion` | `entidad` | `usuario_id` |
|---|---|---|---|
| Registro | `crear` | `organizacion` / `usuario` | el usuario creado |
| Login correcto | `login` | `sesion` | quien entra |
| Contraseña incorrecta | `login_fallido` | `login_fallido` | quien lo intenta |
| Email inexistente | `login_fallido` | `login_fallido` | `NULL` |
| Rate-limit superado | `rate_limit_superado` | `login_fallido` | `NULL` |

En `detalle` van la IP y, en los fallidos, el email que se probó. **Nunca la contraseña ni el
token** — hay una prueba que recorre todos los eventos y lo comprueba.

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
integridad referencial, la unicidad del email por organización, la inmutabilidad del audit log, y
`/v1/auth` (registro, login correcto/incorrecto, rate-limit con auditoría, `/yo`). Los tests de
`/v1/auth` usan una fixture `client` (`tests/conftest.py`) que sustituye `get_db` por la sesión
transaccional de `db_session`, así que las peticiones HTTP de prueba también se revierten al
terminar el test.

Para apuntar a otra base de datos, `DATABASE_URL_TEST`. La suite se niega a arrancar si esa
variable parece apuntar a producción.

## Estructura

```
app/
  main.py          - punto de entrada; monta las rutas bajo /v1 y el logging de peticiones
  core/config.py   - configuración por variables de entorno (pydantic-settings)
  core/db.py       - engine, sesiones y declarative base
  core/logging.py  - logging estructurado (JSON) a stdout
  core/security.py - hash de contraseña, JWT de sesión, dependencia usuario_actual
  core/rate_limit.py - contador simple en memoria del rate-limit (login y registro)
  api/v1/health.py - GET /v1/health
  api/v1/auth.py   - POST /v1/auth/registro, POST /v1/auth/login, GET /v1/auth/yo
  schemas/auth.py  - esquemas Pydantic de /v1/auth
  models/          - modelos SQLAlchemy (organizacion, usuario, evento_auditoria)
  services/        - lógica de escritura; auditoria.py es la única vía al audit log
alembic/versions/  - migraciones
tests/             - pruebas automáticas (contra Postgres)
scripts/init-db.sql      - rol y bases de datos de desarrollo
scripts/crear_organizacion.py - alta de organización + primer usuario (el registro está cerrado)
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

## Pendiente

Fase 0 (T1–T4) cerrada en código. Lo que sigue es la Fase 1 — ver `Plan técnico por fases.md` en la
bóveda (Etapa Entrada: expedientes).

## Nota sobre esta carpeta

Este repositorio vive en `C:\dev\proyecto_API_legal`, **fuera de** OneDrive (a propósito: git y
OneDrive no se llevan bien). Los documentos fuente originales de Juan Diego (Word y Excel) siguen en
`Desktop\Revision de procesos`, sincronizada con OneDrive — esa carpeta ya no tiene código.

## Dónde está el porqué

La bóveda de Obsidian (`Proyectos/API Legal/`) tiene el contexto que este README no repite: la
tesis del proyecto, las decisiones tomadas y por qué, el estado real de cada fase. Este repositorio
es el cómo; la bóveda es el porqué.
