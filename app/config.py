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
    worker_log_file: str = str(BASE_DIR / "logs" / "worker.log")
    worker_log_level: str = "INFO"
    auth_jwt_secret: str = "change-me-in-production"
    auth_jwt_algorithm: str = "HS256"
    auth_access_token_ttl_minutes: int = 15
    auth_refresh_token_ttl_days: int = 14
    auth_issuer: str = "comfyui-wrapper-backend"
    auth_dev_mode: bool = True
    auth_dev_user_id: str = "dev-admin"
    auth_dev_user_roles: str = "admin"
    comfy_models_dir: str = "/app/models"


settings = Settings()
