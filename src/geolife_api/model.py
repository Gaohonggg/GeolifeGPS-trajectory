"""Nạp model version từ MLflow registry và chạy trên điểm của một user."""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass

import mlflow.artifacts
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
        """{"home": ..., "office": ...}, mỗi role là dự đoán hoặc abstain."""
        pred = self.pyfunc.predict(points)
        return {role: _role_result(pred[pred.role == role].iloc[0]) for role in ("home", "office")}


def _role_result(row: pd.Series) -> dict:
    if isinstance(row.abstain_reason, str):
        return {"abstain_reason": row.abstain_reason}
    out = {f: float(row[f]) for f in PLACE_FIELDS}
    missing = [f for f, v in out.items() if math.isnan(v)]
    if missing:
        # contract không cho null trong dự đoán: báo lỗi thay vì trả số sai
        raise ValueError(f"prediction for role {row.role!r} has no value for {missing}")
    out["days"] = int(out["days"])
    return out


def load(uri: str) -> LoadedModel:
    """Tên thuật toán và version config lấy từ metadata của model.

    Ghi thời gian của từng phần (tải, nạp, chạy thử) để đo cold start.
    """
    t0 = time.perf_counter()
    local = mlflow.artifacts.download_artifacts(uri)
    t1 = time.perf_counter()
    # nạp: đọc MLmodel, import code thuật toán đi kèm (code_paths), unpickle
    pyfunc = mlflow.pyfunc.load_model(local)
    meta = pyfunc.metadata.metadata or {}
    model = LoadedModel(ModelInfo(name=meta["algorithm"], version=int(meta["version"])), pyfunc)
    t2 = time.perf_counter()
    # chạy thử để numba biên dịch trước request đầu tiên
    model.predict(synthetic_points())
    t3 = time.perf_counter()
    timings = {"downloadS": round(t1 - t0, 3), "loadS": round(t2 - t1, 3), "warmUpS": round(t3 - t2, 3)}
    log.info("model %s v%s loaded: download %.2fs, load %.2fs, warm-up %.2fs", model.info.name,
             model.info.version, *timings.values(), extra=timings)
    return model


def synthetic_points(days: int = 4) -> pd.DataFrame:
    """Một user giả ở Bắc Kinh: đêm ở nhà, giờ hành chính ở chỗ làm cách ~2 km, mỗi phút một điểm."""
    ts = pd.date_range("2009-03-02 00:00", periods=days * 24 * 60, freq="min")   # UTC; local = UTC+8
    local = ts + pd.Timedelta(hours=8)
    at_work = (local.hour >= 9) & (local.hour < 18)
    lat = np.where(at_work, 39.99, 39.975)
    lon = np.where(at_work, 116.33, 116.31)
    return pd.DataFrame({"user": 0, "ts_utc": ts.astype("datetime64[us]"), "ts_local": local.astype("datetime64[us]"),
                         "tz": "Asia/Shanghai", "lat": lat, "lon": lon})
