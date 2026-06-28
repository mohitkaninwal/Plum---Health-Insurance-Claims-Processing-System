from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[2] / ".env"),
        env_file_encoding="utf-8",
    )

    app_name: str = "Plum Claims API"
    environment: str = "local"
    database_url: str = Field(default="", validation_alias="DATABASE_URL")

    @property
    def database_url_psycopg3(self) -> str:
        """Ensure the URL uses the psycopg3 driver scheme."""
        url = self.database_url
        if url.startswith("postgresql://") or url.startswith("postgres://"):
            url = url.replace("://", "+psycopg://", 1)
        return url
    groq_api_key: str = Field(default="", validation_alias="GROQ_API_KEY")
    cors_origins_raw: str = Field(default="http://localhost:3000", validation_alias="CORS_ORIGINS")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins_raw.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
