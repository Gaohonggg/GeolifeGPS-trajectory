"""Chạy các file db/migrations/*.sql chưa chạy, theo thứ tự tên, mỗi file một transaction.

    DATABASE_URL=postgresql://... python -m geolife_api.migrate
    (hoặc DB_HOST / DB_NAME / DB_USER / DB_PASSWORD, xem config.DbSettings)
"""
from __future__ import annotations

from pathlib import Path

import psycopg

from .config import APP_ROOT, DbSettings

MIGRATIONS = APP_ROOT / "db" / "migrations"


def migrate(url: str, folder: Path = MIGRATIONS) -> list[str]:
    applied = []
    with psycopg.connect(url) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations "
                     "(name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
        conn.commit()
        done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
        for f in sorted(folder.glob("*.sql")):
            if f.name in done:
                continue
            with conn.transaction():
                conn.execute(f.read_text())
                conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (f.name,))
            applied.append(f.name)
    return applied


def main():
    applied = migrate(DbSettings().db_conninfo)
    print("applied:", ", ".join(applied) if applied else "nothing (up to date)")


if __name__ == "__main__":
    main()
