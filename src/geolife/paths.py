"""Đường dẫn chuẩn của repo. Mọi đường dẫn khác được suy ra từ đây."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "Geolife_Trajectories" / "Data"


def preprocess_dir(version: int) -> Path:
    """Output của preprocess version `version`: data/preprocess/v_<version>/."""
    return DATA / "preprocess" / f"v_{version}"


def results_dir(data_version: int, run_name: str) -> Path:
    """Kết quả của một lần chạy model trên dữ liệu preprocess `data_version`."""
    return ROOT / "results" / f"data_v{data_version}" / run_name
