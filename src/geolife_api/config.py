"""Cấu hình của API, đọc từ biến môi trường (tên biến = tên trường viết hoa)."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# src/geolife_api/config.py → gốc repo (ở local) hoặc /app (trong image)
APP_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(protected_namespaces=())

    database_url: str                 # postgresql://user:pass@host:5432/db
    model_uri: str                    # models:/geolife_home_office/1 (cần MLFLOW_TRACKING_URI để tra registry)
    db_pool_size: int = 4
    model_retry_s: float = 5.0        # nạp model lỗi (vd. MLflow chưa lên) thì thử lại sau ngần này giây
    openapi_path: Path = APP_ROOT / "docs" / "openapi.yaml"
