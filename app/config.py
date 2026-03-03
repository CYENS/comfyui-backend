from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./backend.db"
    storage_root: str = "/data/app"
    comfy_base_url: str = "http://127.0.0.1:8188"
    poll_interval_sec: float = 1.0


settings = Settings()
