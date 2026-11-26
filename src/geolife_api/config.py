"""Cấu hình API từ biến môi trường (tên trường viết hoa)."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# gốc repo
APP_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(protected_namespaces=())

    model_uri: str                # models:/<catalog.schema.model>/<version> hoặc s3://…/v=<n>/model
    points_uri: str               # s3://…/data/serving/v_<n> hoặc thư mục local cùng bố cục (geolife_api.export_points)
    model_retry_s: float = 5.0    # chờ giữa các lần thử nạp model
    # Lambda: pha init chờ model tối đa chừng này giây kể từ lúc import handler. Trần của pha init là 10 giây, trong đó
    # ~0,3 giây đã dùng trước khi import (khởi động Python, awslambdaric); phần dư còn lại cho dao động giữa các lần init.
    init_budget_s: float = 8.5
    openapi_path: Path = APP_ROOT / "docs" / "openapi.yaml"
