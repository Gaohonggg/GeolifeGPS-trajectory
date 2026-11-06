"""Interface chung của model và cách đọc config theo version."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

from ..paths import ROOT


def config_path(name: str, version: int) -> Path:
    return ROOT / "models" / name / f"v_{version}" / "config.yaml"


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
