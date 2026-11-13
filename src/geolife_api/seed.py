"""Nạp output của preprocess (points.parquet, users.parquet) vào Postgres bằng COPY theo lô.

    DATABASE_URL=postgresql://... python -m geolife_api.seed --data-dir data/preprocess/v_1 [--replace]
"""
from __future__ import annotations

import argparse
import io
import os
import time
from pathlib import Path

import psycopg
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from pyarrow import csv

COLUMNS = ["user", "ts_utc", "ts_local", "tz", "lat", "lon"]


def seed(url: str, data_dir: Path, split: str = "all", replace: bool = False, batch_size: int = 500_000) -> int:
    # ignore_metadata: pandas metadata trong file đặt "user" làm index
    users = pq.read_table(data_dir / "users.parquet", columns=["user", "split"]).to_pandas(ignore_metadata=True)
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
        pf = pq.ParquetFile(data_dir / "points.parquet")
        with conn.cursor() as cur, cur.copy(
                "COPY gps_points (user_id, ts_utc, ts_local, tz, lat, lon) FROM STDIN (FORMAT csv)") as copy:
            for batch in pf.iter_batches(batch_size=batch_size, columns=COLUMNS):
                t = pa.Table.from_batches([batch]).select(COLUMNS)   # đúng thứ tự cột của lệnh COPY
                t = t.filter(pc.is_in(pc.cast(t["user"], pa.int32()), ids))
                if t.num_rows == 0:
                    continue
                t = t.set_column(COLUMNS.index("tz"), "tz", pc.cast(t["tz"], pa.string()))
                buf = io.BytesIO()
                csv.write_csv(t, buf, csv.WriteOptions(include_header=False))
                copy.write(buf.getvalue())
                n += t.num_rows
                print(f"\r{n:,} points ({time.perf_counter() - t0:.0f}s)", end="", flush=True)
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
    ap.add_argument("--data-dir", type=Path, required=True, help="thư mục output của preprocess, vd. data/preprocess/v_1")
    ap.add_argument("--split", choices=["all", "dev", "holdout"], default="all")
    ap.add_argument("--replace", action="store_true")
    a = ap.parse_args(argv)
    n = seed(os.environ["DATABASE_URL"], a.data_dir, a.split, a.replace)
    print(f"loaded {n:,} points")


if __name__ == "__main__":
    main()
