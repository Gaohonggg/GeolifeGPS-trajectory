from __future__ import annotations

import pandas as pd
import pytest

from geolife.paths import ROOT

RESULTS = ROOT / "results" / "data_v1"
MODEL_VERSIONS = [("stay_point", 1), ("stay_point", 2), ("dbscan", 1), ("dbscan", 2)]


def expected_predictions(name: str, version: int) -> pd.DataFrame:
    """Kết quả chạy hàng loạt của checkpoint 1 (dev + holdout), làm chuẩn để so."""
    files = sorted((RESULTS / f"{name}_v{version}").glob("*/predictions.csv"))
    if not files:
        pytest.skip(f"chưa có results/ cho {name} v{version}")
    return pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
