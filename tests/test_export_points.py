"""Dựng điểm theo user và upload lên S3: ghi một lần, chạy lại không ghi gì, nguồn / nội dung khác thì dừng."""
from __future__ import annotations

import json

import pandas as pd
import pyarrow.parquet as pq
import pytest

from geolife_api import export_points as ep
from geolife_api.export_points import ExportError, build, upload, user_file

from .test_publish import FakeS3

BUCKET = "bucket"


def write_source(d, users=(5, 7), n=10, shuffle=False):
    """Một preprocess v_1 nhỏ: data/preprocess/v_1/points.parquet sort theo (user, ts_utc)."""
    d.mkdir(parents=True, exist_ok=True)
    frames = []
    for u in users:
        ts = pd.date_range("2008-10-23 02:00", periods=n, freq="h").astype("datetime64[us]")
        frames.append(pd.DataFrame({"user": pd.Series(u, index=range(n), dtype="int16"), "traj_id": "t",
                                    "ts_utc": ts, "ts_local": ts + pd.Timedelta(hours=8), "tz": "Asia/Shanghai",
                                    "lat": 40.0 + 0.001 * pd.RangeIndex(n), "lon": 116.3}))
    df = pd.concat(frames, ignore_index=True)
    if shuffle:
        df = df.iloc[::-1]
    df.to_parquet(d / "points.parquet", index=False)
    return d


@pytest.fixture
def src(tmp_path):
    return write_source(tmp_path / "preprocess" / "v_1")


def test_build_writes_one_file_per_user(src, tmp_path):
    out = tmp_path / "serving" / "v_1"
    status, m = build(src, out, 1)
    assert status == "built"
    assert [u["user"] for u in m["users"]] == [5, 7] and m["n_points"] == 20
    assert m["source"]["path"] == "preprocess/v_1/points.parquet"
    assert m["users"][0]["first_ts"] == "2008-10-23T02:00:00Z" and m["users"][0]["last_ts"] == "2008-10-23T11:00:00Z"
    t = pq.read_table(out / user_file(5))
    assert t.schema == ep.SCHEMA and t.num_rows == 10
    assert json.loads((out / "manifest.json").read_text()) == m


def test_rebuild_same_source_writes_nothing(src, tmp_path):
    out = tmp_path / "serving" / "v_1"
    build(src, out, 1)
    mtime = (out / user_file(5)).stat().st_mtime_ns
    status, _ = build(src, out, 1)
    assert status == "already_built" and (out / user_file(5)).stat().st_mtime_ns == mtime


def test_rebuild_other_source_fails(src, tmp_path):
    out = tmp_path / "serving" / "v_1"
    build(src, out, 1)
    write_source(src, users=(5, 7, 9))
    with pytest.raises(ExportError, match="nguồn hoặc định dạng khác"):
        build(src, out, 1)


def test_unsorted_source_fails(tmp_path):
    src = write_source(tmp_path / "preprocess" / "v_1", shuffle=True)
    with pytest.raises(ExportError, match="sort"):
        build(src, tmp_path / "out", 1)


@pytest.fixture
def built(src, tmp_path):
    out = tmp_path / "serving" / "v_1"
    build(src, out, 1)
    return out


def test_upload_writes_files_then_manifest(built):
    s3 = FakeS3()
    status, _ = upload(s3, BUCKET, built)
    assert status == "uploaded"
    assert s3.puts[-1] == "data/serving/v_1/manifest.json"
    assert sorted(s3.puts[:-1]) == ["data/serving/v_1/points/user=5.parquet", "data/serving/v_1/points/user=7.parquet"]
    assert s3.objects["data/serving/v_1/points/user=5.parquet"] == (built / user_file(5)).read_bytes()


def test_reupload_writes_nothing(built):
    s3 = FakeS3()
    upload(s3, BUCKET, built)
    n = len(s3.puts)
    status, _ = upload(s3, BUCKET, built)
    assert status == "already_uploaded" and len(s3.puts) == n


def test_upload_different_content_fails(built):
    s3 = FakeS3()
    upload(s3, BUCKET, built)
    m = json.loads((built / "manifest.json").read_text())
    m["users"][0]["sha256"] = "0" * 64
    (built / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(ExportError, match="nội dung khác"):
        upload(s3, BUCKET, built)


def test_upload_detects_local_file_changed_after_build(built):
    (built / user_file(5)).write_bytes(b"corrupted")
    with pytest.raises(ExportError, match="lệch với manifest"):
        upload(FakeS3(), BUCKET, built)


def test_upload_needs_build(tmp_path):
    with pytest.raises(ExportError, match="chạy build trước"):
        upload(FakeS3(), BUCKET, tmp_path)
