from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "MediReach API"
    environment: str = "development"
    database_url: str = "sqlite:///./medireach.db"
    admin_api_key: str = "change-this-before-deployment"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:5500"
    seed_demo_data: bool = False
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def allowed_origins(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]

@lru_cache
def get_settings() -> Settings:
    return Settings()