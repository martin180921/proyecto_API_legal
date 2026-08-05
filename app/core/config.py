"""Configuracion de la aplicacion, leida de variables de entorno.

Nada de secretos en el codigo — todo por variables de entorno desde el
primer commit (Reglas de trabajo del desarrollador único).
"""
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_env: str = "local"
    log_level: str = "INFO"
    api_v1_prefix: str = "/v1"
    database_url: str = (
        "postgresql+psycopg://api_legal_app:api_legal_app@localhost:5432/api_legal"
    )
    secret_key: str = "cambiar-en-produccion"

    @field_validator("database_url")
    @classmethod
    def _normalizar_driver(cls, valor: str) -> str:
        """Fuerza el driver psycopg (v3), el único que instala este proyecto.

        Railway inyecta `DATABASE_URL` con el esquema `postgresql://` (y algunos
        proveedores todavía usan `postgres://`). SQLAlchemy interpreta ambos
        como «usa psycopg2», que NO está en requirements.txt — así que la app
        arrancaría bien, respondería `/v1/health`, y reventaría con
        `ModuleNotFoundError: psycopg2` en la primera petición que toque la
        base de datos. Un fallo tardío y confuso por un detalle de esquema.

        Reescribirlo aquí, y no en la variable de entorno de Railway, evita
        depender de que alguien recuerde editarla a mano en cada entorno nuevo.
        Verificado contra Postgres 16 el 2026-08-05.
        """
        for prefijo in ("postgresql://", "postgres://"):
            if valor.startswith(prefijo):
                return "postgresql+psycopg://" + valor[len(prefijo) :]
        return valor


settings = Settings()
