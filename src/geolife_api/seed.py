"""Nạp output của preprocess (points.parquet, users.parquet) vào Postgres bằng COPY theo lô.

    DATABASE_URL=postgresql://... python -m geolife_api.seed --data-dir data/preprocess/v_1 [--replace]
    python -m geolife_api.seed --data-dir s3://<bucket>/data/preprocess/v_1   # trên AWS, quyền của task role

Kết nối DB: `DATABASE_URL` hoặc DB_HOST / DB_NAME / DB_USER / DB_PASSWORD (config.DbSettings).
"""
from __future__ import annotations

import argparse
import io
import sys
import time

import psycopg
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from pyarrow import csv
from pyarrow import fs as pafs

from .config import DbSettings

COLUMNS = ["user", "ts_utc", "ts_local", "tz", "lat", "lon"]


def open_dir(data_dir: str) -> tuple[pafs.FileSystem, str]:
    """Thư mục local hoặc `s3://bucket/prefix`. S3 dùng chuỗi credential mặc định của AWS (profile, task role)."""
    if "://" not in data_dir:
        return pafs.LocalFileSystem(), str(pafs.LocalFileSystem().normalize_path(data_dir))
    filesystem, path = pafs.FileSystem.from_uri(data_dir)
    return filesystem, path.rstrip("/")


def progress(prev: int, n: int, elapsed: float, every: int = 2_000_000) -> None:
    """Terminal: ghi đè một dòng. Log (CloudWatch, file): một dòng mỗi khi vượt qua bội số của `every` điểm."""
    if sys.stdout.isatty():
        print(f"\r{n:,} points ({elapsed:.0f}s)", end="", flush=True)
    elif n // every > prev // every:
        print(f"{n:,} points ({elapsed:.0f}s)", flush=True)


def seed(url: str, data_dir: str, split: str = "all", replace: bool = False, batch_size: int = 500_000) -> int:
    filesystem, root = open_dir(data_dir)
    # ignore_metadata: pandas metadata trong file đặt "user" làm index
    users = pq.read_table(f"{root}/users.parquet", columns=["user", "split"], filesystem=filesystem) \
        .to_pandas(ignore_metadata=True)
    if split != "all":
        users = users[users.split == split]
    ids = pa.array(users.user.astype("int32"))

    with psycopg.connect(url) as conn:
        conn.execute("SET TIME ZONE 'UTC'")   # ts_utc trong parquet là naive UTC
        if conn.execute("SELECT EXISTS (SELECT 1 FROM users)").fetchone()[0]:
            if not replace:
                raise SystemExit("bảng users đã có dữ liệu; dùng --replace để nạp lại")
            conn.execute("TRUNCATE users, gps_points")

        with conn.cursor() as cur:
            cur.executemany("INSERT INTO users (user_id, split) VALUES (%s, %s)",
                            list(zip(users.user.astype(int), users.split)))

        n, t0 = 0, time.perf_counter()
        with filesystem.open_input_file(f"{root}/points.parquet") as f, conn.cursor() as cur, cur.copy(
                "COPY gps_points (user_id, ts_utc, ts_local, tz, lat, lon) FROM STDIN (FORMAT csv)") as copy:
            # pre_buffer=False: mặc định pyarrow đọc trước và giữ toàn bộ file nén (~600 MB) tới hết vòng lặp
            for batch in pq.ParquetFile(f, pre_buffer=False).iter_batches(batch_size=batch_size, columns=COLUMNS):
                t = pa.Table.from_batches([batch]).select(COLUMNS)   # đúng thứ tự cột của lệnh COPY
                t = t.filter(pc.is_in(pc.cast(t["user"], pa.int32()), ids))
                if t.num_rows == 0:
                    continue
                t = t.set_column(COLUMNS.index("tz"), "tz", pc.cast(t["tz"], pa.string()))
                buf = io.BytesIO()
                csv.write_csv(t, buf, csv.WriteOptions(include_header=False))
                copy.write(buf.getvalue())
                prev, n = n, n + t.num_rows
                progress(prev, n, time.perf_counter() - t0)
        if sys.stdout.isatty():
            print()

        conn.execute("""
            UPDATE users u SET n_points = s.n, first_ts = s.first_ts, last_ts = s.last_ts
            FROM (SELECT user_id, count(*) AS n, min(ts_utc) AS first_ts, max(ts_utc) AS last_ts
                  FROM gps_points GROUP BY user_id) s
            WHERE u.user_id = s.user_id""")
        conn.commit()
        conn.execute("ANALYZE users")
        conn.execute("ANALYZE gps_points")
    return n


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True,
                    help="output của preprocess: thư mục local (data/preprocess/v_1) hoặc s3://bucket/data/preprocess/v_1")
    ap.add_argument("--split", choices=["all", "dev", "holdout"], default="all")
    ap.add_argument("--replace", action="store_true")
    a = ap.parse_args(argv)
    n = seed(DbSettings().db_conninfo, a.data_dir, a.split, a.replace)
    print(f"loaded {n:,} points")


if __name__ == "__main__":
    main()
