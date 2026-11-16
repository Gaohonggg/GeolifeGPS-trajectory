"""Cấu hình API từ biến môi trường (tên trường viết hoa)."""
from __future__ import annotations

from pathlib import Path

from psycopg.conninfo import make_conninfo
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# gốc repo ở local, /app trong image
APP_ROOT = Path(__file__).resolve().parents[2]


class DbSettings(BaseSettings):
    """Kết nối Postgres: `DATABASE_URL` (local), hoặc `DB_HOST` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` tách rời.

    Trên AWS mật khẩu do RDS sinh, nằm trong Secrets Manager và được ECS tiêm vào `DB_PASSWORD`; ghép thành URL thì
    phải escape, nên các phần được giữ riêng tới lúc tạo chuỗi kết nối.
    """
    model_config = SettingsConfigDict(protected_namespaces=())

    database_url: str | None = None
    db_host: str | None = None
    db_port: int = 5432
    db_name: str | None = None
    db_user: str | None = None
    db_password: str | None = None

    @model_validator(mode="after")
    def _one_source(self):
        parts = {"DB_HOST": self.db_host, "DB_NAME": self.db_name, "DB_USER": self.db_user,
                 "DB_PASSWORD": self.db_password}
        if self.database_url is None:
            missing = [k for k, v in parts.items() if not v]
            if missing:
                raise ValueError(f"đặt DATABASE_URL, hoặc đủ DB_HOST / DB_NAME / DB_USER / DB_PASSWORD (thiếu {missing})")
        elif any(parts.values()):
            raise ValueError("chỉ đặt một trong hai: DATABASE_URL hoặc DB_HOST / DB_NAME / DB_USER / DB_PASSWORD")
        return self

    @property
    def db_conninfo(self) -> str:
        """Chuỗi kết nối cho psycopg."""
        if self.database_url is not None:
            return self.database_url
        return make_conninfo(host=self.db_host, port=self.db_port, dbname=self.db_name, user=self.db_user,
                             password=self.db_password)


class Settings(DbSettings):
    model_uri: str                # models:/<catalog.schema.model>/<version> hoặc s3://…/v=<n>/model
    db_pool_size: int = 4
    model_retry_s: float = 5.0    # chờ giữa các lần thử nạp model
    openapi_path: Path = APP_ROOT / "docs" / "openapi.yaml"
