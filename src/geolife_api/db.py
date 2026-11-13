"""Đọc điểm GPS của user từ Postgres."""
from __future__ import annotations

import io
from datetime import datetime

import pandas as pd
import pyarrow as pa
from psycopg import Connection, Error, sql
from psycopg_pool import ConnectionPool, PoolTimeout
from pyarrow import csv

# input của model (geolife.models.base.POINT_COLS)
POINT_TYPES = {"user": pa.int32(), "ts_utc": pa.timestamp("us"), "ts_local": pa.timestamp("us"), "tz": pa.string(),
               "lat": pa.float64(), "lon": pa.float64()}


def _configure(conn: Connection) -> None:
    # timestamptz luôn theo UTC, không phụ thuộc cấu hình server
    conn.execute("SET TIME ZONE 'UTC'")
    conn.commit()


class Database:
    def __init__(self, url: str, pool_size: int = 4):
        # open=False: app vẫn khởi động khi DB chưa lên
        self.pool = ConnectionPool(url, min_size=1, max_size=pool_size, configure=_configure, open=False)

    def open(self) -> None:
        self.pool.open(wait=False)

    def close(self) -> None:
        self.pool.close()

    def ping(self, timeout: float = 2.0) -> bool:
        try:
            with self.pool.connection(timeout=timeout) as conn:
                conn.execute("SELECT 1")
            return True
        except (PoolTimeout, Error):
            return False

    def user_exists(self, user_id: int) -> bool:
        with self.pool.connection() as conn:
            return conn.execute("SELECT 1 FROM users WHERE user_id = %s", (user_id,)).fetchone() is not None

    def fetch_points(self, user_id: int, start: datetime | None = None, end: datetime | None = None) -> pd.DataFrame:
        """Điểm trong [start, end), sort theo thời gian, ts_utc dạng naive UTC.

        Dùng COPY + pyarrow thay vì fetch từng dòng: một user có thể có hàng triệu điểm.
        """
        where = [sql.SQL("user_id = {}").format(sql.Literal(user_id))]
        if start is not None:
            where.append(sql.SQL("ts_utc >= {}").format(sql.Literal(start)))
        if end is not None:
            where.append(sql.SQL("ts_utc < {}").format(sql.Literal(end)))
        query = sql.SQL(
            "COPY (SELECT user_id AS \"user\", ts_utc AT TIME ZONE 'UTC' AS ts_utc, ts_local, tz, lat, lon "
            "FROM gps_points WHERE {} ORDER BY ts_utc) TO STDOUT (FORMAT csv, HEADER)"
        ).format(sql.SQL(" AND ").join(where))
        with self.pool.connection() as conn, conn.cursor() as cur:
            buf = io.BytesIO()
            with cur.copy(query) as copy:
                for chunk in copy:
                    buf.write(chunk)
        buf.seek(0)
        table = csv.read_csv(buf, convert_options=csv.ConvertOptions(column_types=POINT_TYPES))
        return table.to_pandas()   # tz giữ dạng chuỗi: signature không nhận category
