"""Model tìm home / office. Mỗi model có version, tham số ở `models/<tên>/v_<k>/config.yaml`.

    from geolife.models import load_model
    model = load_model("stay_point", version=1)
    stays, pred = model.predict(points)
"""
from __future__ import annotations

from .base import Model, load_config
from .dbscan import DbscanModel
from .stay_point import StayPointModel

REGISTRY: dict[str, type[Model]] = {m.name: m for m in [StayPointModel, DbscanModel]}


def load_model(name: str, version: int, **overrides) -> Model:
    """Model với tham số của một version; overrides (vd. D_m=100) chỉ dùng khi tuning."""
    return REGISTRY[name].from_config(load_config(name, version), **overrides)
