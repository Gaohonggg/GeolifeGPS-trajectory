"""API chạy model cho từng user một; checkpoint 1 chạy hàng loạt. Hai cách phải cho cùng kết quả.

Chạy lại 4 model version trên toàn bộ 182 user, mỗi lần một user, rồi so với results/ (dev + holdout).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from geolife import io
from geolife.models import load_model
from geolife.paths import preprocess_dir

from .conftest import MODEL_VERSIONS, expected_predictions

pytestmark = pytest.mark.slow
NUM = ["lat", "lon", "hours", "days", "confidence", "regularity", "margin"]


@pytest.fixture(scope="module")
def points():
    if not (preprocess_dir(1) / "points.parquet").exists():
        pytest.skip("chưa có data/preprocess/v_1")
    return io.load_points(1)


def compare(got: pd.DataFrame, want: pd.DataFrame) -> None:
    key = ["user", "role"]
    got = got.sort_values(key).reset_index(drop=True)
    want = want.sort_values(key).reset_index(drop=True)
    assert got[key].equals(want[key].astype(got[key].dtypes.to_dict()))
    assert (got.abstain_reason.fillna("") == want.abstain_reason.fillna("")).all()
    assert (got.place.to_numpy() == want.place.to_numpy()).all()
    np.testing.assert_allclose(got[NUM].to_numpy(float), want[NUM].to_numpy(float), rtol=1e-9, atol=1e-9)


@pytest.mark.parametrize(("name", "version"), MODEL_VERSIONS)
def test_per_user_matches_batch(points, name, version):
    model = load_model(name, version)
    preds = [model.predict(g)[1] for _, g in points.groupby("user", sort=True)]
    compare(pd.concat(preds, ignore_index=True), expected_predictions(name, version))
