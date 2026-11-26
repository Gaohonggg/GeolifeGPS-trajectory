"""Chọn Lambda version cho alias live theo cấu hình và model (scripts/promote.py)."""
from __future__ import annotations

import importlib.util
import sys

from geolife.paths import ROOT

_spec = importlib.util.spec_from_file_location("promote", ROOT / "scripts" / "promote.py")
promote = importlib.util.module_from_spec(_spec)
# dataclass tra module của class qua sys.modules
sys.modules["promote"] = promote
_spec.loader.exec_module(promote)
Box, find_box = promote.Box, promote.find_box

CFG_A, CFG_B = '{"image": "repo@sha256:aaa"}', '{"image": "repo@sha256:bbb"}'
V1, V3 = "s3://b/models/m/v=1/model", "s3://b/models/m/v=3/model"


def test_no_function_yet_means_new_version():
    assert find_box([], CFG_A, V1, prefer=[None]) is None


def test_keeps_version_already_on_live():
    boxes = [Box("1", CFG_A, V1), Box("2", CFG_A, V1)]
    assert find_box(boxes, CFG_A, V1, prefer=[1]) == 1


def test_reuses_newest_matching_version_for_rollback():
    # live đang ở version 3 (v3); @champion về v1: dùng lại version cũ thay vì đóng mới
    boxes = [Box("1", CFG_A, V1), Box("2", CFG_A, V1), Box("3", CFG_A, V3)]
    assert find_box(boxes, CFG_A, V1, prefer=[3]) == 2


def test_version_with_other_config_is_not_reused():
    boxes = [Box("1", CFG_A, V1)]
    assert find_box(boxes, CFG_B, V1, prefer=[1]) is None


def test_latest_is_never_chosen():
    assert find_box([Box("$LATEST", CFG_A, V1)], CFG_A, V1, prefer=[None]) is None


def test_model_uri_matches_stack_layout():
    uri = promote.model_uri("geolife-1-artifacts", "workspace.geolife.geolife_home_office", 3)
    assert uri == "s3://geolife-1-artifacts/models/geolife_home_office/v=3/model"
