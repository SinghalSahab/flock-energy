import os
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    portal_url: str = Field(default="https://urja-ops.flockenergy.tech", alias="PORTAL_URL")
    portal_username: str = Field(default="", alias="PORTAL_USERNAME")
    portal_password: str = Field(default="", alias="PORTAL_PASSWORD")

    cache_ttl_seconds: int = Field(default=300, alias="CACHE_TTL_SECONDS")
    request_timeout_seconds: float = Field(default=15.0, alias="REQUEST_TIMEOUT_SECONDS")
    db_path: str = Field(default=":memory:", alias="DB_PATH")

    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


def get_settings() -> Settings:
    return Settings()
