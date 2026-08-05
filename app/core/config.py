"""Configuracion de la aplicacion, leida de variables de entorno.

Nada de secretos en el codigo — todo por variables de entorno desde el
primer commit (Reglas de trabajo del desarrollador único).
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_env: str = "local"
    log_level: str = "INFO"
    api_v1_prefix: str = "/v1"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/api_legal"
    secret_key: str = "cambiar-en-produccion"


settings = Settings()
