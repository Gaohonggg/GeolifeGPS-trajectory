"""Cấu hình API từ biến môi trường (tên trường viết hoa)."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# gốc repo ở local, /app trong image
APP_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(protected_namespaces=())

    database_url: str
    model_uri: str                # models:/<catalog.schema.model>/<version>
    db_pool_size: int = 4
    model_retry_s: float = 5.0    # chờ giữa các lần thử nạp model
    openapi_path: Path = APP_ROOT / "docs" / "openapi.yaml"
