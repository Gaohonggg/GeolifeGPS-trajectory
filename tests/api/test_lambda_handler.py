"""Handler Lambda nhận event HTTP API payload v2 như API Gateway gửi và trả response đúng contract."""
from __future__ import annotations

import json
import threading
import time

import pytest

from geolife_api import lambda_handlers
from geolife_api.lambda_handlers import make_handler
from geolife_api.main import State, create_app

from .test_routes import PLACE, FakeModel, FakeStore, points


def http_api_event(method: str, path: str, query: str = "") -> dict:
    """Event mà API Gateway (HTTP API, payload v2, stage `$default`) gửi cho Lambda."""
    params = dict(p.split("=", 1) for p in query.split("&")) if query else None
    event = {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": path,
        "rawQueryString": query,
        "headers": {"host": "abc123.execute-api.ap-southeast-1.amazonaws.com", "user-agent": "curl/8.7.1",
                    "content-length": "0"},
        "requestContext": {
            "accountId": "123456789012", "apiId": "abc123",
            "domainName": "abc123.execute-api.ap-southeast-1.amazonaws.com",
            "domainPrefix": "abc123", "requestId": "Xyz123=", "routeKey": "$default", "stage": "$default",
            "time": "25/Nov/2026:03:00:00 +0000", "timeEpoch": 1795575600000,
            "http": {"method": method, "path": path, "protocol": "HTTP/1.1", "sourceIp": "203.0.113.7",
                     "userAgent": "curl/8.7.1"},
        },
        "isBase64Encoded": False,
    }
    if params:
        event["queryStringParameters"] = params
    return event


class Context:
    """Phần của LambdaContext mà Mangum đọc."""
    aws_request_id = "req-1"
    function_name = "geolife-api"


@pytest.fixture
def handler():
    model = FakeModel({"home": PLACE, "office": {"abstain_reason": "insufficient_workdays"}})
    return make_handler(create_app(state=State(FakeStore({5: points()}), model)))


def call(handler, method, path, query=""):
    r = handler(http_api_event(method, path, query), Context())
    return r["statusCode"], json.loads(r["body"]), r["headers"]


def test_health(handler):
    status, body, _ = call(handler, "GET", "/v1/health")
    assert status == 200 and body == {"status": "ok", "model_loaded": True, "data_available": True}


def test_predict(handler):
    status, body, headers = call(handler, "POST", "/v1/users/5/predictions", "start=2008-10-23T03:00:00Z")
    assert status == 200 and headers["content-type"] == "application/json"
    assert body["user_id"] == 5 and body["n_points"] == 2
    assert body["time_range"] == {"start": "2008-10-23T03:00:00Z", "end": "2008-10-23T04:00:00Z"}
    assert body["home"] == PLACE and body["office"] == {"abstain_reason": "insufficient_workdays"}


@pytest.mark.parametrize(("path", "query", "status", "code"), [
    ("/v1/users/999/predictions", "", 404, "user_not_found"),
    ("/v1/users/5/predictions", "start=not-a-date", 400, "invalid_request"),
    ("/v1/users/5/predictions", "start=2008-10-24T00:00:00Z&end=2008-10-23T00:00:00Z", 400, "invalid_time_range"),
    ("/v1/users/abc/predictions", "", 400, "invalid_request"),
])
def test_errors_follow_contract(handler, path, query, status, code):
    got_status, body, _ = call(handler, "POST", path, query)
    assert got_status == status and body["error"]["code"] == code and body["error"]["message"]


def test_unknown_path(handler):
    status, _, _ = call(handler, "GET", "/v1/nope")
    assert status == 404


def test_cold_start_header_only_on_first_response(handler):
    _, _, first = call(handler, "GET", "/v1/health")
    _, _, second = call(handler, "GET", "/v1/health")
    assert first["x-cold-start"] == "1" and "x-cold-start" not in second


@pytest.fixture
def lambda_env(monkeypatch, tmp_path):
    """Biến môi trường của function; `_handlers` rỗng để mỗi test chạy lại pha init; hạn init tính từ lúc test bắt đầu."""
    monkeypatch.setenv("MODEL_URI", "s3://bucket/models/geolife_home_office/v=1/model")
    monkeypatch.setenv("POINTS_URI", str(tmp_path))
    (tmp_path / "manifest.json").write_text("{}")
    monkeypatch.setattr(lambda_handlers, "_handlers", {})
    monkeypatch.setattr(lambda_handlers, "_IMPORT_START", time.perf_counter())
    return monkeypatch


def fake_loads(monkeypatch, *outcomes):
    """Thay model_lib.load: lần gọi thứ i chạy `outcomes[i]` (None: trả model ngay; hàm: chạy rồi trả model)."""
    calls = []
    it = iter(outcomes)

    def load(uri):
        calls.append(uri)
        outcome = next(it)
        if outcome is not None:
            outcome()
        return FakeModel({"home": PLACE, "office": PLACE})

    monkeypatch.setattr(lambda_handlers.model_lib, "load", load)
    return calls


def fail_after(event: threading.Event):
    def run():
        event.wait(5)
        raise OSError("S3 unavailable")
    return run


def test_init_reads_settings_and_loads_model_once(lambda_env):
    calls = fake_loads(lambda_env, None)
    h = lambda_handlers.api
    assert lambda_handlers.api is h
    assert calls == ["s3://bucket/models/geolife_home_office/v=1/model"]
    status, body, _ = call(h, "GET", "/v1/health")
    assert status == 200 and body["model_loaded"] is True


def test_init_ends_at_budget_and_first_request_waits_for_model(lambda_env):
    lambda_env.setenv("INIT_BUDGET_S", "0.2")
    release = threading.Event()
    fake_loads(lambda_env, lambda: release.wait(5))

    t0 = time.perf_counter()
    h = lambda_handlers.api
    assert time.perf_counter() - t0 < 1        # pha init không chờ model quá hạn
    threading.Timer(0.3, release.set).start()   # model nạp xong sau khi init đã kết thúc
    status, body, headers = call(h, "POST", "/v1/users/5/predictions")
    assert status == 404 and body["error"]["code"] == "user_not_found"   # request đã tới model/nguồn điểm, không phải 503
    assert headers["x-cold-start"] == "1"


def test_load_failing_during_init_is_retried_before_first_request(lambda_env):
    done = threading.Event()
    done.set()
    calls = fake_loads(lambda_env, fail_after(done), None)   # lỗi ngay, trong hạn của pha init
    h = lambda_handlers.api
    status, body, _ = call(h, "GET", "/v1/health")
    assert status == 200 and body["model_loaded"] is True
    assert len(calls) == 2


def test_load_failing_after_init_answers_503_then_next_request_reloads(lambda_env):
    lambda_env.setenv("INIT_BUDGET_S", "0.1")
    fail = threading.Event()
    calls = fake_loads(lambda_env, fail_after(fail), None)
    h = lambda_handlers.api
    fail.set()
    status, body, _ = call(h, "POST", "/v1/users/5/predictions")
    assert status == 503 and body["error"]["code"] == "model_unavailable"
    status, body, _ = call(h, "GET", "/v1/health")
    assert status == 200 and body["model_loaded"] is True
    assert len(calls) == 2


def test_unknown_attribute():
    with pytest.raises(AttributeError):
        lambda_handlers.worker
