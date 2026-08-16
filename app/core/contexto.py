"""Contexto de la petición actual, compartido entre el middleware de
`app/main.py` y `app/services/auditoria.py` (Bloque A2, 2026-08-16).

Vive en su propio módulo, y no en `app/main.py`, para evitar un import
circular: `app/services/auditoria.py` lo necesita para escribir `request_id`
en el `detalle` de cada evento, y `app/main.py` importa (indirectamente, vía
los routers) a `app/services/auditoria.py`.

Los `contextvars` se propagan *hacia dentro*: el valor fijado por el
middleware antes de `call_next` está visible en todo el código que atiende
esa petición, incluido un endpoint síncrono ejecutado en el threadpool de
FastAPI. No se propagan *hacia fuera* — nada fijado dentro de un endpoint
sería visible de vuelta en el middleware tras `call_next`. Por eso el único
escritor de `id_peticion_actual` es el middleware, nunca un endpoint.
"""
from contextvars import ContextVar

id_peticion_actual: ContextVar[str | None] = ContextVar("id_peticion_actual", default=None)
