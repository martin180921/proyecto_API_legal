"""Configuracion de la aplicacion, leida de variables de entorno.

Nada de secretos en el codigo — todo por variables de entorno desde el
primer commit (Reglas de trabajo del desarrollador único).
"""
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Valores de ejemplo que circulan por el repositorio público (`.env.example`, el
# default de abajo). Ninguno sirve para firmar un JWT de verdad.
CLAVES_DE_EJEMPLO = frozenset({"cambiar-en-produccion", "", "changeme"})

# HS256 firma con HMAC-SHA256: por debajo de 32 bytes la clave tiene menos
# entropía que el propio hash. Es también el mínimo que recomienda RFC 7518 §3.2.
LONGITUD_MINIMA_SECRET_KEY = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # Sin esto, pydantic añade `input_value={...}` al texto de cualquier
        # ValidationError — o sea, vuelca un fragmento de la configuración en
        # los logs. Y esta configuración contiene secretos: la `DATABASE_URL`
        # lleva la contraseña de Postgres, y `SECRET_KEY` firma los JWT. Un
        # error de validación no puede ser la vía por la que un secreto acaba
        # en los logs de Railway (regla de T4: ni contraseñas ni tokens).
        # Comprobado el 2026-08-08: sin este flag, el mensaje incluía el final
        # de la SECRET_KEY rechazada.
        hide_input_in_errors=True,
    )

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

    @model_validator(mode="after")
    def _exigir_secret_key_real_en_produccion(self) -> "Settings":
        """Se niega a arrancar en producción con la clave de ejemplo.

        Sin esto el fallo es silencioso y total: el default
        `cambiar-en-produccion` está en el repositorio **público**, así que si
        T4 se despliega sin la variable real la app arranca, `/v1/health`
        responde 200, el healthcheck de Railway pasa — y cualquiera que lea el
        repo puede firmar un JWT válido para cualquier organización. No hay
        ningún síntoma que delate el problema hasta que alguien lo explota.

        Es el mismo criterio que el normalizador de driver de arriba: se
        resuelve en el código, no confiando en que alguien recuerde poner la
        variable en cada entorno nuevo. Fallar al importar la configuración
        hace que el pre-deploy y el healthcheck de Railway tumben el despliegue,
        que es exactamente lo que se quiere.

        Fuera de `production` no valida nada: en local y en CI la clave de
        ejemplo es la correcta y estorbar ahí no aporta seguridad ninguna.
        """
        if self.app_env != "production":
            return self

        # El valor de la clave NUNCA entra en el mensaje: este ValueError acaba
        # en los logs de Railway (regla de T4: ni contraseñas ni tokens en los
        # logs). Se dice qué pasa y cómo arreglarlo, no cuál es el valor malo.
        if (
            self.secret_key in CLAVES_DE_EJEMPLO
            or len(self.secret_key) < LONGITUD_MINIMA_SECRET_KEY
        ):
            raise ValueError(
                "SECRET_KEY no sirve con APP_ENV=production: es uno de los valores "
                f"de ejemplo del repositorio o mide menos de {LONGITUD_MINIMA_SECRET_KEY} "
                "caracteres. Genera una clave real con\n"
                '    python -c "import secrets; print(secrets.token_urlsafe(64))"\n'
                "y ponla como variable de entorno SECRET_KEY en el servicio de "
                "Railway — nunca en el repositorio ni en la bóveda."
            )
        return self


settings = Settings()
