from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite:///./backend.db"
    storage_root: str = "/data/app"
    comfy_base_url: str = "http://127.0.0.1:8188"
    poll_interval_sec: float = 1.0


settings = Settings()
