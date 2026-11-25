"""S3PointStore: đọc đúng điểm của user trong [start, end), ở thư mục local và qua S3 (giả), chỉ đọc row group cần."""
from __future__ import annotations

import io
from datetime import UTC, datetime

import pandas as pd
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from fastapi.testclient import TestClient

from geolife import io as gio
from geolife.paths import preprocess_dir, serving_dir
from geolife_api import export_points as ep
from geolife_api.main import State, create_app
from geolife_api.points import S3PointStore
from geolife_api.service import DataUnavailable

from ..test_export_points import write_source
from .test_routes import FakeModel

N = 20_000
PREFIX = "data/serving/v_1/"


@pytest.fixture
def built(tmp_path, monkeypatch):
    """Bản dựng nhỏ: user 5 và 7, mỗi user 20 000 điểm cách nhau 1 giờ, row group 2 000 dòng.

    File đủ lớn (~0,4 MB) để phần đọc footer của pyarrow (64 KB cuối file) không phủ cả file.
    """
    monkeypatch.setattr(ep, "FORMAT", {**ep.FORMAT, "row_group_size": 2_000})
    src = write_source(tmp_path / "preprocess" / "v_1", n=N)
    out = tmp_path / "serving" / "v_1"
    ep.build(src, out, 1)
    return out


class FakeS3:
    """head_object / get_object có Range trên các file của một thư mục; đếm số GET và số byte đã tải."""

    def __init__(self, root, error=None):
        self.root, self.error = root, error
        self.gets, self.bytes = 0, 0

    def _path(self, key):
        if self.error is not None:
            raise self.error
        p = self.root / key.removeprefix(PREFIX)
        if not p.is_file():
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return p

    def head_object(self, Bucket, Key):
        return {"ContentLength": self._path(Key).stat().st_size}

    def get_object(self, Bucket, Key, Range=None):
        data = self._path(Key).read_bytes()
        if Range is not None:
            a, b = (int(x) for x in Range.removeprefix("bytes=").split("-"))
            data = data[a:b + 1]
        self.gets += 1
        self.bytes += len(data)
        return {"Body": io.BytesIO(data)}


def stores(built):
    s3 = FakeS3(built)
    return [S3PointStore(str(built)), S3PointStore(f"s3://bucket/{PREFIX}", s3=s3)]


def utc(s):
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


@pytest.mark.parametrize("kind", ["local", "s3"])
@pytest.mark.parametrize(("start", "end", "n"), [
    (None, None, N),
    ("2008-10-25T02:00:00", None, N - 48),
    (None, "2008-10-25T02:00:00", 48),
    ("2008-10-25T02:00:00", "2008-10-25T05:00:00", 3),
    ("2020-01-01T00:00:00", None, 0),
])
def test_fetch_points_in_range(built, kind, start, end, n):
    store = stores(built)[kind == "s3"]
    df = store.fetch_points(5, start and utc(start), end and utc(end))
    assert len(df) == n
    assert list(df.columns) == ["user", "ts_utc", "ts_local", "lat", "lon", "tz"]
    assert df.ts_utc.is_monotonic_increasing and (df.user == 5).all()
    if n:
        assert start is None or df.ts_utc.iloc[0] == pd.Timestamp(start)
        assert end is None or df.ts_utc.iloc[-1] < pd.Timestamp(end)


def test_s3_reads_only_needed_row_groups(built):
    full, part = FakeS3(built), FakeS3(built)
    S3PointStore(f"s3://bucket/{PREFIX}", s3=full).fetch_points(5)
    S3PointStore(f"s3://bucket/{PREFIX}", s3=part).fetch_points(5, utc("2008-10-25T02:00:00"),
                                                              utc("2008-10-25T05:00:00"))
    # 3 điểm nằm trong 1 trên 10 row group
    assert part.bytes < full.bytes / 3


@pytest.mark.parametrize("kind", ["local", "s3"])
def test_user_exists_and_ping(built, kind):
    store = stores(built)[kind == "s3"]
    assert store.user_exists(5) and not store.user_exists(999)
    assert store.ping()
    (built / "manifest.json").unlink()
    assert not store.ping()


@pytest.mark.parametrize("error", [ClientError({"Error": {"Code": "403"}}, "HeadObject"),
                                   EndpointConnectionError(endpoint_url="https://s3")])
def test_s3_errors_are_data_unavailable(built, error):
    store = S3PointStore(f"s3://bucket/{PREFIX}", s3=FakeS3(built, error=error))
    assert not store.ping()
    with pytest.raises(DataUnavailable):
        store.user_exists(5)


def test_api_returns_503_when_data_unavailable(built):
    store = S3PointStore(f"s3://bucket/{PREFIX}", s3=FakeS3(built, error=ClientError({"Error": {"Code": "403"}}, "x")))
    with TestClient(create_app(state=State(store, FakeModel({})))) as c:
        r = c.post("/v1/users/5/predictions")
        h = c.get("/v1/health")
    assert r.status_code == 503 and r.json()["error"]["code"] == "data_unavailable"
    assert h.status_code == 503 and h.json()["data_available"] is False


# ---- trên bản dựng thật (make serving-points) ----

USERS = [83, 14, 153]     # trung vị, phân vị 90, lớn nhất theo số điểm


@pytest.fixture(scope="module")
def real_store():
    if not (serving_dir(1) / "manifest.json").exists() or not (preprocess_dir(1) / "points.parquet").exists():
        pytest.skip("chưa có data/serving/v_1 (make serving-points)")
    return S3PointStore(str(serving_dir(1)))


def _source(user):
    df = gio.load_points(1, users=[user], columns=["user", "ts_utc", "ts_local", "lat", "lon", "tz"])
    return df.reset_index(drop=True)


@pytest.mark.parametrize("user", USERS)
def test_matches_preprocess(real_store, user):
    src = _source(user)
    mid = src.ts_utc.iloc[len(src) // 2]
    late = src.ts_utc.iloc[3 * len(src) // 4]
    for start, end in [(None, None), (mid, None), (None, mid), (mid, late)]:
        keep = pd.Series(True, index=src.index)
        if start is not None:
            keep &= src.ts_utc >= start
        if end is not None:
            keep &= src.ts_utc < end
        want = src[keep]
        got = real_store.fetch_points(user, start and start.to_pydatetime().replace(tzinfo=UTC),
                                      end and end.to_pydatetime().replace(tzinfo=UTC))
        assert len(got) == len(want) > 0
        for c in ["user", "ts_utc", "ts_local", "lat", "lon"]:
            assert (got[c].to_numpy() == want[c].to_numpy()).all(), (user, c)
        assert (got.tz.astype(str).to_numpy() == want.tz.astype(str).to_numpy()).all()
