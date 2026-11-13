"""Test trên stack docker đang chạy (make setup): contract và kết quả end-to-end qua DB + registry.

    API_URL=http://localhost:8000 uv run pytest -m integration
"""
from __future__ import annotations

import os

import httpx
import numpy as np
import pytest
import schemathesis
from schemathesis.specs.openapi.checks import ignored_auth, positive_data_acceptance

from geolife.paths import ROOT

from ..conftest import expected_predictions

API_URL = os.environ.get("API_URL", "http://localhost:8000")
pytestmark = pytest.mark.integration


def _api_up() -> bool:
    try:
        return httpx.get(f"{API_URL}/v1/health", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


if not _api_up():
    pytest.skip(f"API không chạy ở {API_URL}", allow_module_level=True)

schema = schemathesis.openapi.from_path(ROOT / "docs" / "openapi.yaml")
schema.config.update(base_url=f"{API_URL}/v1")


@schema.parametrize()
def test_contract(case):
    response = case.call(timeout=120)
    # Xác thực chưa bật ở bước này (spec đã khai báo OAuth2), nên bỏ check "API bỏ qua auth"
    excluded = [ignored_auth]
    if response.status_code == 400 and response.json()["error"]["code"] == "invalid_time_range":
        # start >= end hợp lệ theo schema (OpenAPI không diễn tả được ràng buộc giữa hai tham số) nhưng spec yêu cầu 400
        excluded.append(positive_data_acceptance)
    case.validate_response(response, excluded_checks=excluded)


def test_every_user_matches_batch_results():
    """Mọi user trong DB: kết quả của API khớp predictions.csv của đúng model version đang serve."""
    first = httpx.post(f"{API_URL}/v1/users/5/predictions", timeout=120).json()
    name, version = first["model"]["name"], first["model"]["version"]
    want = expected_predictions(name, version).set_index(["user", "role"])
    with httpx.Client(base_url=f"{API_URL}/v1", timeout=300) as c:
        for user in sorted(want.index.get_level_values("user").unique()):
            body = c.post(f"/users/{user}/predictions").json()
            for role in ("home", "office"):
                got, exp = body[role], want.loc[(user, role)]
                if isinstance(exp.abstain_reason, str):
                    assert got == {"abstain_reason": exp.abstain_reason}, (user, role)
                else:
                    keys = ["lat", "lon", "hours", "days", "confidence", "regularity", "margin"]
                    np.testing.assert_allclose([got[k] for k in keys], exp[keys].to_numpy(float),
                                               rtol=1e-9, err_msg=f"user {user} {role}")
