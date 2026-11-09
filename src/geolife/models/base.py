"""Phần chung của mọi model: interface, cách đọc config theo version, và hợp đồng dữ liệu giữa model với các bước sau.

- Input: bảng điểm (các cột của points.parquet), duyệt theo từng user bằng `iter_users`.
- Output của bước tìm nơi ở lại: bảng có đúng các cột `STAY_COLS` (stay của stay_point, visit của dbscan), cộng cột `place`.
  Mọi bước sau (`home_office`, `confidence`, `evaluation`) chỉ dựa vào hợp đồng này.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from ..paths import ROOT

STAY_COLS = ["user", "i0", "i1", "start_utc", "end_utc", "start_local", "end_local", "lat", "lon", "n_points", "dur_h", "tz"]


@dataclass
class UserSeq:
    """Chuỗi điểm của một user dưới dạng mảng. ts, loc: giây kể từ epoch theo UTC và theo giờ local."""
    user: int
    lat: np.ndarray
    lon: np.ndarray
    ts: np.ndarray
    loc: np.ndarray
    tz: np.ndarray


def iter_users(points: pd.DataFrame):
    """points phải sort theo (user, ts_utc), như points.parquet."""
    ts = points.ts_utc.to_numpy().astype("datetime64[s]").astype(np.int64).astype(np.float64)
    loc = points.ts_local.to_numpy().astype("datetime64[s]").astype(np.int64).astype(np.float64)
    lat, lon, tz = points.lat.to_numpy(), points.lon.to_numpy(), points.tz.astype(str).to_numpy()
    for u, idx in points.groupby("user", sort=True).indices.items():
        yield UserSeq(int(u), lat[idx], lon[idx], ts[idx], loc[idx], tz[idx])


def config_path(name: str, version: int) -> Path:
    return ROOT / "models_tuning" / name / f"v_{version}" / "config.yaml"


def load_config(name: str, version: int) -> dict:
    cfg = yaml.safe_load(config_path(name, version).read_text())
    assert cfg["name"] == name and cfg["version"] == version, f"config không khớp {name} v_{version}"
    return cfg


class Model:
    name: str = ""

    def __init__(self, params: dict, version: int | None = None, data_version: int | None = None):
        self.params = params
        self.version = version
        self.data_version = data_version

    @classmethod
    def from_config(cls, cfg: dict, **overrides):
        return cls({**cfg["params"], **overrides}, cfg["version"], cfg["data_version"])

    @property
    def run_name(self) -> str:
        return f"{self.name}_v{self.version}"

    def predict(self, points: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        """points: các cột của points.parquet. Trả về (bảng stay có cột place, dự đoán theo (user, role))."""
        raise NotImplementedError
