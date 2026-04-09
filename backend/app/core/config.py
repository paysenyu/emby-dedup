"""Core configuration values for Phase 1."""

import os

from pydantic import BaseModel


class Settings(BaseModel):
    """Application runtime settings loaded from environment variables."""

    db_path: str = os.getenv("APP_DB_PATH", "/config/app.db")
    sqlite_url: str = os.getenv("APP_SQLITE_URL", f"sqlite:///{db_path}")
    config_path: str = os.getenv("APP_CONFIG_PATH", "/config/config.json")
    logs_dir: str = os.getenv("APP_LOG_DIR", os.getenv("APP_LOGS_DIR", "config/logs"))


settings = Settings()
