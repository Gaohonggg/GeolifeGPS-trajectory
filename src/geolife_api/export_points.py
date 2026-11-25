"""Dựng điểm GPS theo user cho API (`data/serving/v_<n>/`) từ preprocess v_<n>, rồi upload lên S3.

    uv run python -m geolife_api.export_points build --version 1
    uv run python -m geolife_api.export_points upload --version 1 [--bucket geolife-<account_id>-artifacts]

Bố cục giống nhau ở local và trên S3 (`s3://<bucket>/data/serving/v_<n>/`), định nghĩa trong `geolife_api.points`:

    points/user=<id>.parquet   cột theo POINT_COLS, thứ tự (ts_utc) như points.parquet; zstd; row group 131 072 dòng
    manifest.json              nguồn (đường dẫn + SHA-256), định dạng, mỗi user: số điểm, first_ts, last_ts, SHA-256

Mỗi user một file để API chỉ tải dữ liệu của user đó; row group nhỏ có thống kê `ts_utc`, nên request có
`start` / `end` chỉ đọc các row group giao với khoảng đó.

Ghi một lần như bản phát hành model (`geolife.publish`): `manifest.json` ghi sau cùng, có manifest thì bản dựng mới
hoàn chỉnh. Chạy lại `build` khi đã có manifest thì so nguồn và định dạng; `upload` khi S3 đã có manifest thì so
checksum từng file. Khớp thì không ghi gì, lệch thì dừng với lỗi (dữ liệu khác thì dùng data version mới).

Chạy ở máy local, nơi có dữ liệu preprocess; API không import module này.
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from geolife.paths import preprocess_dir, serving_dir
from geolife.publish import default_bucket, put_file, put_manifest_once, read_manifest, sha256

from .points import MANIFEST, user_file

# input của model (geolife.models.base.POINT_COLS); tz là chuỗi vì signature của model không nhận category
SCHEMA = pa.schema([("user", pa.int16()), ("ts_utc", pa.timestamp("us")), ("ts_local", pa.timestamp("us")),
                    ("lat", pa.float64()), ("lon", pa.float64()), ("tz", pa.string())])
FORMAT = {"compression": "zstd", "row_group_size": 131_072}
UPLOAD_THREADS = 8


class ExportError(Exception):
    pass


def _ts(t) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def split_by_user(table: pa.Table) -> list[tuple[int, pa.Table]]:
    """Bảng sort theo (user, ts_utc) → [(user, bảng của user)], cắt không copy."""
    user = table["user"].to_numpy()
    ts = table["ts_utc"].to_numpy()
    if len(user) and not np.all((user[1:] > user[:-1]) | ((user[1:] == user[:-1]) & (ts[1:] >= ts[:-1]))):
        raise ExportError("points.parquet phải sort theo (user, ts_utc)")
    bounds = np.concatenate([[0], np.flatnonzero(user[1:] != user[:-1]) + 1, [len(user)]])
    return [(int(user[a]), table.slice(a, b - a)) for a, b in zip(bounds[:-1], bounds[1:])]


def _manifest_matches(existing: dict, source: dict, out: Path) -> None:
    if existing["source"]["sha256"] != source["sha256"] or existing["format"] != FORMAT:
        raise ExportError(f"{out} đã dựng từ nguồn hoặc định dạng khác; không ghi đè, hãy dùng data version mới")


def build(src: Path, out: Path, data_version: int) -> tuple[str, dict]:
    """Dựng `out` từ `src/points.parquet`. Trả về ("built" | "already_built", manifest)."""
    source_path = src / "points.parquet"
    source = {"path": f"{src.parent.name}/{src.name}/points.parquet", "sha256": sha256(source_path)}
    manifest_path = out / MANIFEST
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text())
        _manifest_matches(existing, source, out)
        return "already_built", existing

    table = pq.read_table(source_path, columns=SCHEMA.names).cast(SCHEMA)
    (out / "points").mkdir(parents=True, exist_ok=True)
    users = []
    for user_id, t in split_by_user(table):
        path = out / user_file(user_id)
        pq.write_table(t, path, **FORMAT)
        users.append({"user": user_id, "n_points": t.num_rows, "first_ts": _ts(t["ts_utc"][0].as_py()),
                      "last_ts": _ts(t["ts_utc"][-1].as_py()), "size": path.stat().st_size,
                      "sha256": sha256(path)})

    manifest = {"data_version": data_version, "source": source, "format": FORMAT,
                "schema": {f.name: str(f.type) for f in SCHEMA},
                "n_users": len(users), "n_points": sum(u["n_points"] for u in users),
                "built_at": datetime.now(UTC).isoformat(timespec="seconds"), "users": users}
    # mode "x": hai lần build chạy song song thì lần sau báo lỗi thay vì ghi đè
    with manifest_path.open("x") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    return "built", manifest


def _check_local(out: Path, manifest: dict) -> None:
    """File ở local còn đúng như manifest (không bị sửa sau khi dựng)."""
    bad = [u["user"] for u in manifest["users"] if sha256(out / user_file(u["user"])) != u["sha256"]]
    if bad:
        raise ExportError(f"file của user {bad[:5]} trong {out} lệch với manifest.json; hãy dựng lại")


def _same_files(a: dict, b: dict) -> bool:
    return {u["user"]: u["sha256"] for u in a["users"]} == {u["user"]: u["sha256"] for u in b["users"]}


def upload(s3, bucket: str, out: Path) -> tuple[str, dict]:
    """Upload bản dựng ở `out` lên `s3://bucket/data/serving/v_<n>/`. Trả về ("uploaded" | "already_uploaded", manifest)."""
    manifest_path = out / MANIFEST
    if not manifest_path.exists():
        raise ExportError(f"{out} chưa có manifest.json; chạy build trước")
    manifest = json.loads(manifest_path.read_text())
    prefix = f"data/serving/v_{manifest['data_version']}/"
    uri = f"s3://{bucket}/{prefix}"

    existing = read_manifest(s3, bucket, prefix + MANIFEST)
    if existing is not None:
        if not _same_files(existing, manifest):
            raise ExportError(f"{uri} đã có với nội dung khác; không ghi đè, hãy dùng data version mới")
        return "already_uploaded", existing

    _check_local(out, manifest)
    with ThreadPoolExecutor(UPLOAD_THREADS) as pool:
        list(pool.map(lambda u: put_file(s3, bucket, prefix + user_file(u["user"]), out / user_file(u["user"]),
                                         u["sha256"]), manifest["users"]))
    if not put_manifest_once(s3, bucket, prefix + MANIFEST, manifest):
        existing = read_manifest(s3, bucket, prefix + MANIFEST)
        if not _same_files(existing, manifest):
            raise ExportError(f"{uri} vừa được ghi với nội dung khác")
        return "already_uploaded", existing
    return "uploaded", manifest


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["build", "upload"])
    ap.add_argument("--version", type=int, default=1, help="data version (preprocess v_<n>)")
    ap.add_argument("--bucket", help="upload: mặc định geolife-<account_id>-artifacts")
    a = ap.parse_args(argv)

    out = serving_dir(a.version)
    try:
        if a.command == "build":
            status, m = build(preprocess_dir(a.version), out, a.version)
            label = "đã có, không ghi gì" if status == "already_built" else "dựng xong"
            print(f"{out}: {label} ({m['n_users']} user, {m['n_points']} điểm)")
        else:
            import boto3

            session = boto3.Session()
            bucket = a.bucket or default_bucket(session)
            status, m = upload(session.client("s3"), bucket, out)
            label = "đã có, không ghi gì" if status == "already_uploaded" else "upload xong"
            print(f"s3://{bucket}/data/serving/v_{m['data_version']}/: {label} ({m['n_users']} user)")
    except ExportError as e:
        raise SystemExit(f"lỗi: {e}") from None


if __name__ == "__main__":
    main()
