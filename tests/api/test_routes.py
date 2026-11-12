"""Phần HTTP của API với DB và model giả: mã trả về và định dạng lỗi đúng contract."""
from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from psycopg import OperationalError

from geolife_api.main import State, create_app
from geolife_api.model import LoadedModel
from geolife_api.schemas import ModelInfo

PLACE = {"lat": 40.0, "lon": 116.3, "hours": 10.0, "days": 3, "confidence": 0.9, "regularity": 0.5, "margin": 1.0}


class FakeDb:
    def __init__(self, users=None, up=True):
        self.users = users or {}
        self.up = up

    def ping(self):
        return self.up

    def user_exists(self, user_id):
        return user_id in self.users

    def fetch_points(self, user_id, start=None, end=None):
        df = self.users[user_id]
        if start is not None:
            df = df[df.ts_utc >= start.replace(tzinfo=None)]
        if end is not None:
            df = df[df.ts_utc < end.replace(tzinfo=None)]
        return df


class FakeModel(LoadedModel):
    def __init__(self, result):
        super().__init__(ModelInfo(name="stay_point", version=1), pyfunc=None)
        self.result = result

    def predict(self, points):
        return self.result


def points(n=3):
    ts = pd.date_range("2008-10-23 02:00", periods=n, freq="h").astype("datetime64[us]")
    return pd.DataFrame({"user": 5, "ts_utc": ts, "ts_local": ts, "tz": "Asia/Shanghai", "lat": 40.0, "lon": 116.3})


def client(db=None, result=None, loaded=True):
    model = FakeModel(result or {"home": PLACE, "office": {"abstain_reason": "insufficient_workdays"}}) if loaded else None
    state = State(db or FakeDb({5: points()}), model)
    return TestClient(create_app(state=state))


def error_code(resp):
    return resp.json()["error"]["code"]


def test_predict_ok():
    with client() as c:
        r = c.post("/v1/users/5/predictions")
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == 5 and body["n_points"] == 3
    assert body["time_range"] == {"start": "2008-10-23T02:00:00Z", "end": "2008-10-23T04:00:00Z"}
    assert body["model"] == {"name": "stay_point", "version": 1}
    assert body["home"] == PLACE
    assert body["office"] == {"abstain_reason": "insufficient_workdays"}


@pytest.mark.parametrize(("path", "code"), [
    ("/v1/users/-1/predictions", "invalid_request"),
    ("/v1/users/abc/predictions", "invalid_request"),
    ("/v1/users/5/predictions?start=not-a-date", "invalid_request"),
    ("/v1/users/5/predictions?start=0.5", "invalid_request"),                   # số không phải date-time
    ("/v1/users/5/predictions?start=2008-10-23", "invalid_request"),            # thiếu giờ và offset
    ("/v1/users/5/predictions?start=2008-10-23T00:00:00", "invalid_request"),   # thiếu offset
    ("/v1/users/5/predictions?start=2008-10-24T00:00:00Z&end=2008-10-23T00:00:00Z", "invalid_time_range"),
    ("/v1/users/5/predictions?start=2008-10-23T00:00:00Z&end=2008-10-23T00:00:00Z", "invalid_time_range"),
])
def test_bad_request(path, code):
    with client() as c:
        r = c.post(path)
    assert r.status_code == 400 and error_code(r) == code


def test_not_found():
    with client() as c:
        assert error_code(c.post("/v1/users/999/predictions")) == "user_not_found"
        r = c.post("/v1/users/5/predictions?start=2010-01-01T00:00:00Z&end=2010-02-01T00:00:00Z")
    assert r.status_code == 404 and error_code(r) == "no_points"


def test_large_utc_offset_is_converted():
    with client() as c:
        r = c.post("/v1/users/5/predictions?start=2008-10-23T21:00:00%2B18:30")   # = 02:30Z
    assert r.status_code == 200 and r.json()["n_points"] == 2


def test_time_range_filters_points():
    with client() as c:
        r = c.post("/v1/users/5/predictions?start=2008-10-23T03:00:00Z")
    assert r.json()["n_points"] == 2


def test_model_loading():
    with client(loaded=False) as c:
        r = c.post("/v1/users/5/predictions")
        h = c.get("/v1/health")
    assert r.status_code == 503 and error_code(r) == "model_unavailable"
    assert h.status_code == 503 and h.json() == {"status": "unavailable", "model_loaded": False, "db_connected": True}


def test_health():
    with client() as c:
        assert c.get("/v1/health").json() == {"status": "ok", "model_loaded": True, "db_connected": True}
    with client(db=FakeDb(up=False)) as c:
        assert c.get("/v1/health").status_code == 503


def test_db_down():
    class Down(FakeDb):
        def user_exists(self, user_id):
            raise OperationalError("connection refused")

    with client(db=Down({5: points()})) as c:
        r = c.post("/v1/users/5/predictions")
    assert r.status_code == 503 and r.json()["error"]["code"] == "db_unavailable"


def test_unexpected_error_hides_details():
    class Broken(FakeDb):
        def fetch_points(self, *a, **k):
            raise RuntimeError("secret internals")

    with TestClient(create_app(state=State(Broken({5: points()}), FakeModel({}))), raise_server_exceptions=False) as c:
        r = c.post("/v1/users/5/predictions")
    assert r.status_code == 500 and r.json() == {"error": {"code": "internal_error", "message": "unexpected error"}}


def test_docs_serve_contract():
    with client() as c:
        spec = c.get("/openapi.json").json()
    assert "/users/{userId}/predictions" in spec["paths"]
