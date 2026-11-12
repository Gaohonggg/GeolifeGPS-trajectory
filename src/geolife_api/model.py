"""Nạp một model version từ MLflow registry và chạy nó trên điểm của một user."""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import mlflow.pyfunc
import numpy as np
import pandas as pd

from .schemas import ModelInfo

log = logging.getLogger(__name__)

PLACE_FIELDS = ["lat", "lon", "hours", "days", "confidence", "regularity", "margin"]


@dataclass
class LoadedModel:
    info: ModelInfo
    pyfunc: mlflow.pyfunc.PyFuncModel

    def predict(self, points: pd.DataFrame) -> dict[str, dict]:
        """Kết quả theo role: {"home": {...}, "office": {...}}, mỗi role là dự đoán hoặc abstain."""
        pred = self.pyfunc.predict(points)
        return {role: _role_result(pred[pred.role == role].iloc[0]) for role in ("home", "office")}


def _role_result(row: pd.Series) -> dict:
    if isinstance(row.abstain_reason, str):
        return {"abstain_reason": row.abstain_reason}
    out = {f: float(row[f]) for f in PLACE_FIELDS}
    missing = [f for f, v in out.items() if math.isnan(v)]
    if missing:
        # contract không cho phép null trong một dự đoán: báo lỗi thay vì trả số sai
        raise ValueError(f"prediction for role {row.role!r} has no value for {missing}")
    out["days"] = int(out["days"])
    return out


def load(uri: str) -> LoadedModel:
    """uri: models:/geolife_home_office/<version> hoặc .../@<alias>. Thuật toán và version của config lấy từ metadata lúc
    đăng ký."""
    pyfunc = mlflow.pyfunc.load_model(uri)
    meta = pyfunc.metadata.metadata or {}
    model = LoadedModel(ModelInfo(name=meta["algorithm"], version=int(meta["version"])), pyfunc)
    _warm_up(model)
    return model


def _warm_up(model: LoadedModel) -> None:
    """Chạy model một lần trên dữ liệu giả để numba biên dịch trước, request đầu tiên không phải chờ."""
    model.predict(synthetic_points())
    log.info("model %s v%s warmed up", model.info.name, model.info.version)


def synthetic_points(days: int = 4) -> pd.DataFrame:
    """Một user giả ở Bắc Kinh: đêm ở nhà, giờ hành chính ở chỗ làm cách ~2 km, mỗi phút một điểm."""
    ts = pd.date_range("2009-03-02 00:00", periods=days * 24 * 60, freq="min")   # UTC; local = UTC+8
    local = ts + pd.Timedelta(hours=8)
    at_work = (local.hour >= 9) & (local.hour < 18)
    lat = np.where(at_work, 39.99, 39.975)
    lon = np.where(at_work, 116.33, 116.31)
    return pd.DataFrame({"user": 0, "ts_utc": ts.astype("datetime64[us]"), "ts_local": local.astype("datetime64[us]"),
                         "tz": pd.Categorical(["Asia/Shanghai"] * len(ts)), "lat": lat, "lon": lon})
