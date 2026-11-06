"""Gom các stay của một user thành place (địa điểm).

Cách gom: duyệt stay theo thời lượng giảm dần; stay chưa thuộc place nào trở thành tâm của place mới và kéo theo mọi stay chưa
gán nằm trong bán kính eps quanh nó. Khác DBSCAN (min_samples = 1) ở chỗ place không thể "nối chuỗi" dài vô hạn: mọi stay
của place nằm trong eps quanh tâm, nên toạ độ của place không bị kéo vào giữa hai nơi khác nhau.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree

from .geo import EARTH_R


def leader_clusters(lat: np.ndarray, lon: np.ndarray, weight: np.ndarray, eps_m: float) -> np.ndarray:
    n = len(lat)
    label = np.full(n, -1, dtype=np.int64)
    if n == 0:
        return label
    X = np.radians(np.c_[lat, lon])
    nb = BallTree(X, metric="haversine").query_radius(X, r=eps_m / EARTH_R)
    k = 0
    for i in np.argsort(-weight, kind="stable"):
        if label[i] >= 0:
            continue
        m = nb[i][label[nb[i]] < 0]
        label[m] = k
        k += 1
    return label


def assign_places(stays: pd.DataFrame, eps_m: float) -> pd.Series:
    """Mã place (theo từng user) của mỗi stay."""
    place = np.full(len(stays), -1, dtype=np.int64)
    for _, idx in stays.groupby("user").indices.items():
        s = stays.iloc[idx]
        place[idx] = leader_clusters(s.lat.to_numpy(), s.lon.to_numpy(), s.dur_h.to_numpy(), eps_m)
    return pd.Series(place, index=stays.index, name="place")
