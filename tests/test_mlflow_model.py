"""Model đóng gói thành pyfunc, nạp lại từ registry, phải cho đúng kết quả của model gốc."""
from __future__ import annotations

import mlflow
import pandas as pd
import pytest

from geolife import register
from geolife.models import load_model
from geolife_api.model import load, synthetic_points

URI = f"models:/{register.MODEL_NAME}"


@pytest.fixture
def local_registry(tmp_path, monkeypatch):
    # mlflow-skinny không có backend sqlite, nên test dùng file store (MLflow 3 phải bật cờ mới cho dùng)
    uri = (tmp_path / "mlruns").as_uri()
    monkeypatch.setenv("MLFLOW_ALLOW_FILE_STORE", "true")
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    mlflow.set_tracking_uri(uri)
    mlflow.set_registry_uri(uri)
    yield mlflow.MlflowClient()
    mlflow.set_tracking_uri(None)


def test_register_and_load(local_registry):
    client = local_registry
    assert register.register("stay_point", 1, client) == "1"
    assert register.register("dbscan", 1, client) == "2"      # mọi thuật toán chung một registered model
    assert register.register("stay_point", 1, client) == "1"  # lần hai: bỏ qua, không tạo version mới
    assert register.registered(client) == {("stay_point", 1): "1", ("dbscan", 1): "2"}

    m = load(f"{URI}/2")
    assert (m.info.name, m.info.version) == ("dbscan", 1)
    pts = synthetic_points()
    got = m.pyfunc.predict(pts)
    want = load_model("dbscan", 1).predict(pts)[1]
    pd.testing.assert_frame_equal(got.reset_index(drop=True), want.reset_index(drop=True))
    assert "abstain_reason" not in m.predict(pts)["home"]


def test_register_rejects_skipped_version(local_registry):
    with pytest.raises(SystemExit, match="phải đăng ký v1 trước v2"):
        register.register("dbscan", 2, local_registry)


def test_register_without_eval(local_registry, monkeypatch):
    # chưa có kết quả holdout: vẫn đăng ký, chỉ không có metric
    monkeypatch.setattr(register, "load_metrics", lambda *a: None)
    assert register.register("stay_point", 1, local_registry) == "1"
    run = local_registry.get_run(local_registry.get_model_version(register.MODEL_NAME, "1").run_id)
    assert run.data.metrics == {}


def test_register_rejects_stale_eval(local_registry, monkeypatch):
    real = register.load_metrics
    monkeypatch.setattr(register, "load_metrics", lambda *a: {**real(*a), "params": {"D_m": 1}})
    with pytest.raises(SystemExit, match="không chạy bằng tham số hiện tại"):
        register.register("stay_point", 1, local_registry)
