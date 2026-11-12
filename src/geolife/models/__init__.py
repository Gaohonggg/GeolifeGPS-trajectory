"""Model tìm home / office. Mỗi model có version, tham số ở `models/<tên>/v_<k>/config.yaml`.

    from geolife.models import load_model
    model = load_model("stay_point", version=1)
    stays, pred = model.predict(points)
"""
from __future__ import annotations

from .base import Model, load_config
from .dbscan import DbscanModel
from .stay_point import StayPointModel

# Thứ tự = thứ tự phát triển; `geolife.register` đăng ký lên MLflow theo thứ tự này. Thuật toán mới thêm vào cuối.
REGISTRY: dict[str, type[Model]] = {m.name: m for m in [StayPointModel, DbscanModel]}


def load_model(name: str, version: int, **overrides) -> Model:
    """Model với tham số của một version; overrides (vd. D_m=100) chỉ dùng khi tuning."""
    if name not in REGISTRY:
        raise ValueError(f"model phải là một trong {sorted(REGISTRY)}, nhận được {name!r}")
    return REGISTRY[name].from_config(load_config(name, version), **overrides)
