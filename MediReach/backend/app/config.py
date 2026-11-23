from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    app_name: str = "MediReach API"
    environment: str = "development"
    database_url: str = "sqlite:///./medireach.db"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:5500"
    seed_demo_data: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def sqlalchemy_database_url(self) -> str:
        """Use the explicitly installed psycopg 3 driver for PostgreSQL URLs."""
        url = make_url(self.database_url)
        if url.drivername in {"postgres", "postgresql"}:
            return url.set(drivername="postgresql+psycopg").render_as_string(
                hide_password=False
            )
        return self.database_url

    @model_validator(mode="after")
    def validate_production_settings(self):
        if self.environment.strip().lower() not in {"prod", "production"}:
            return self

        try:
            database_url = make_url(self.database_url)
        except Exception as exc:
            raise ValueError(
                "Production DATABASE_URL must be a valid PostgreSQL connection URL."
            ) from exc

        if (
            database_url.drivername
            not in {"postgres", "postgresql", "postgresql+psycopg"}
            or not database_url.host
            or not database_url.database
        ):
            raise ValueError(
                "Production requires a PostgreSQL DATABASE_URL with a host and database."
            )

        origins = self.allowed_origins
        if not origins:
            raise ValueError("Production requires at least one exact HTTPS CORS origin.")

        for origin in origins:
            parsed = urlsplit(origin)
            try:
                parsed.port
            except ValueError as exc:
                raise ValueError("Production CORS_ORIGINS contains an invalid origin.") from exc

            if (
                origin == "*"
                or parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "Production CORS_ORIGINS must contain exact HTTPS origins without paths."
                )

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
