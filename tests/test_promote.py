"""Chọn Lambda version cho alias live / challenger theo cấu hình và model (scripts/promote.py).

Các test `test_case_<n>` đi theo bảng trường hợp của `make aws-promote` trong docs triển khai. Trạng thái xuất phát
chung: kệ có A (v1) và B (v3) cùng image hiện tại; live = A, challenger = B (live chia canary_weight % sang B);
registry @champion = v1, @challenger = v3. Lambda version ghi bằng số: A = 1, B = 2, C = 3…
"""
from __future__ import annotations

import importlib.util
import sys

import pytest

from geolife.paths import ROOT

_spec = importlib.util.spec_from_file_location("promote", ROOT / "scripts" / "promote.py")
promote = importlib.util.module_from_spec(_spec)
# dataclass tra module của class qua sys.modules
sys.modules["promote"] = promote
_spec.loader.exec_module(promote)
Box, Labels, find_box = promote.Box, promote.Labels, promote.find_box

CFG_A, CFG_B = '{"image": "repo@sha256:aaa"}', '{"image": "repo@sha256:bbb"}'
V1, V3 = "s3://b/models/m/v=1/model", "s3://b/models/m/v=3/model"
A, B, C, D = 1, 2, 3, 4


class Shelf:
    """Kệ giả: hộp đóng thêm mang image hiện tại và số version tăng dần."""

    def __init__(self, boxes: list[tuple[int, int]], image: str = CFG_A):
        self.boxes = [Box(str(v), CFG_A, f"v{m}") for v, m in boxes]
        self.image = image
        self.closed: list[int] = []

    def push_image(self, image: str, model: int) -> None:
        """Như `terraform apply` đầu tiên sau khi push image mới: $LATEST đổi image nên Lambda đóng một hộp."""
        self.image = image
        self.close(model)

    def find(self, model: int, prefer: list[int | None]) -> int | None:
        return find_box(self.boxes, self.image, f"v{model}", prefer)

    def close(self, model: int) -> int:
        v = max((int(b.lambda_version) for b in self.boxes), default=0) + 1
        self.boxes.append(Box(str(v), self.image, f"v{model}"))
        self.closed.append(model)
        return v


def promote_with(shelf: Shelf, champion: int | None, challenger: int | None,
                 current: Labels | None = Labels(A, B)) -> Labels:
    champion, challenger = promote.registry_targets(champion, challenger)
    return promote.assign_labels(champion, challenger, current, shelf.find, shelf.close)


@pytest.fixture
def shelf() -> Shelf:
    return Shelf([(A, 1), (B, 3)])


def test_case_1_new_challenger_closes_one_box(shelf):
    assert promote_with(shelf, 1, 4) == Labels(A, C)
    assert shelf.closed == [4]


def test_case_2_both_new_closes_champion_first(shelf):
    assert promote_with(shelf, 2, 4) == Labels(C, D)
    assert shelf.closed == [2, 4]


def test_case_3_challenger_becomes_champion_with_new_challenger(shelf):
    assert promote_with(shelf, 3, 4) == Labels(B, C)
    assert shelf.closed == [4]


def test_case_4_finalize_canary_reuses_challenger_box(shelf):
    assert promote_with(shelf, 3, None) == Labels(B, B)
    assert shelf.closed == []


def test_case_5_cancel_canary_keeps_old_box(shelf):
    assert promote_with(shelf, 1, None) == Labels(A, A)
    assert shelf.closed == []


def test_case_6_new_champion_keeps_challenger_box(shelf):
    assert promote_with(shelf, 2, 3) == Labels(C, B)
    assert shelf.closed == [2]


def test_case_7_rollback_after_finalize_reuses_old_box(shelf):
    # đã chốt v3: live = challenger = B; @champion về v1
    assert promote_with(shelf, 1, None, current=Labels(B, B)) == Labels(A, A)
    assert shelf.closed == []


def test_case_7_rollback_with_other_image_closes_new_box(shelf):
    shelf.push_image(CFG_B, 3)                       # C: v3 với image mới
    assert promote_with(shelf, 1, None, current=Labels(C, C)) == Labels(D, D)
    assert shelf.closed == [3, 1]


def test_case_8_challenger_equal_to_champion_means_no_canary(shelf):
    assert promote_with(shelf, 1, 1) == Labels(A, A)
    assert shelf.closed == []


def test_case_9_nothing_changed(shelf):
    assert promote_with(shelf, 1, 3) == Labels(A, B)
    assert shelf.closed == []


def test_case_10_no_champion_stops():
    with pytest.raises(SystemExit):
        promote.registry_targets(None, 3)


def test_case_11_new_image_closes_both_boxes(shelf):
    # $LATEST chứa v3 (challenger đóng sau cùng); apply đầu tiên đóng C (v3, image mới)
    shelf.push_image(CFG_B, 3)
    assert promote_with(shelf, 1, 3) == Labels(D, C)
    assert shelf.closed == [3, 1]


def test_live_box_is_preferred_over_challenger_box():
    shelf = Shelf([(A, 1), (B, 1)])
    assert promote_with(shelf, 1, None, current=Labels(A, B)) == Labels(A, A)
    assert promote_with(shelf, 1, None, current=Labels(B, A)) == Labels(B, B)


def test_challenger_box_is_preferred_over_older_boxes():
    shelf = Shelf([(A, 3), (B, 1), (C, 3)])
    assert promote_with(shelf, 3, None, current=Labels(B, A)) == Labels(A, A)


def test_current_labels_from_tfvars():
    assert promote.current_labels({}) is None
    assert promote.current_labels({"live": {"lambda_version": 6, "model_version": 1}}) == Labels(6, 6)
    assert promote.current_labels({"live": {"lambda_version": 6, "model_version": 1},
                                   "challenger": {"lambda_version": 7, "model_version": 3}}) == Labels(6, 7)


def test_no_function_yet_means_new_version():
    assert find_box([], CFG_A, V1, prefer=[None]) is None


def test_version_with_other_config_is_not_reused():
    boxes = [Box("1", CFG_A, V1)]
    assert find_box(boxes, CFG_B, V1, prefer=[1]) is None


def test_latest_is_never_chosen():
    assert find_box([Box("$LATEST", CFG_A, V1)], CFG_A, V1, prefer=[None]) is None


def test_model_uri_matches_stack_layout():
    uri = promote.model_uri("geolife-1-artifacts", "workspace.geolife.geolife_home_office", 3)
    assert uri == "s3://geolife-1-artifacts/models/geolife_home_office/v=3/model"
