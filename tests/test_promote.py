"""Xếp model version vào hai slot blue / green theo alias (scripts/promote.py)."""
from __future__ import annotations

import importlib.util

from geolife.paths import ROOT

_spec = importlib.util.spec_from_file_location("promote", ROOT / "scripts" / "promote.py")
promote = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(promote)
assign = promote.assign


def state(blue, green, live="blue", weight=0):
    return {"blue_model_version": blue, "green_model_version": green, "live_slot": live, "canary_weight": weight}


def test_first_promote_puts_champion_on_blue():
    assert assign({}, champion=1, challenger=None) == state(1, None)


def test_challenger_goes_to_other_slot_with_zero_weight():
    assert assign(state(1, None), champion=1, challenger=3) == state(1, 3)


def test_repromote_keeps_canary_weight():
    assert assign(state(1, 3, weight=50), champion=1, challenger=3) == state(1, 3, weight=50)


def test_new_challenger_resets_weight():
    assert assign(state(1, 3, weight=50), champion=1, challenger=4) == state(1, 4)


def test_finished_canary_switches_live_slot():
    # canary lên 100%, alias chuyển: v3 @champion, không còn @challenger
    assert assign(state(1, 3, weight=100), champion=3, challenger=None) == state(None, 3, live="green")


def test_next_release_after_switch_uses_blue_as_canary_slot():
    assert assign(state(None, 3, live="green"), champion=3, challenger=4) == state(4, 3, live="green")


def test_no_challenger_stops_other_slot():
    assert assign(state(1, 3, weight=10), champion=1, challenger=None) == state(1, None)


def test_challenger_equal_to_champion_is_ignored():
    assert assign(state(1, None), champion=1, challenger=1) == state(1, None)
