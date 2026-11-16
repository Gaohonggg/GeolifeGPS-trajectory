"""Cấu hình DB: DATABASE_URL hoặc các phần tách rời, không nhận cả hai."""
from __future__ import annotations

import pytest
from psycopg.conninfo import conninfo_to_dict
from pydantic import ValidationError

from geolife_api.config import DbSettings

DB_VARS = ["DATABASE_URL", "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in DB_VARS:
        monkeypatch.delenv(k, raising=False)


def test_database_url_is_used_as_is(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/geolife")
    assert DbSettings().db_conninfo == "postgresql://u:p@localhost:5432/geolife"


def test_parts_are_escaped(monkeypatch):
    # mật khẩu do RDS sinh có thể chứa ký tự đặc biệt
    password = "a b'c@d/e:f"
    for k, v in {"DB_HOST": "db.example", "DB_NAME": "geolife", "DB_USER": "geolife", "DB_PASSWORD": password}.items():
        monkeypatch.setenv(k, v)
    info = conninfo_to_dict(DbSettings().db_conninfo)
    assert info == {"host": "db.example", "port": "5432", "dbname": "geolife", "user": "geolife", "password": password}


def test_missing_parts_fail(monkeypatch):
    monkeypatch.setenv("DB_HOST", "db.example")
    with pytest.raises(ValidationError, match="DB_PASSWORD"):
        DbSettings()


def test_both_sources_fail(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/geolife")
    monkeypatch.setenv("DB_HOST", "db.example")
    with pytest.raises(ValidationError, match="chỉ đặt một"):
        DbSettings()
