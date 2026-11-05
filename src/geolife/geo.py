"""Khoảng cách trên mặt cầu."""
from __future__ import annotations

import numpy as np
from numba import njit

EARTH_R = 6_371_008.8  # m


def haversine(lat1, lon1, lat2, lon2):
    """Khoảng cách (m) giữa hai mảng toạ độ (độ)."""
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(x, dtype=np.float64)) for x in (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_R * np.arcsin(np.sqrt(a))


@njit(cache=True)
def hav(lat1, lon1, lat2, lon2):
    """Khoảng cách (m) giữa hai điểm (độ), dùng bên trong hàm numba."""
    r = np.pi / 180
    a = np.sin((lat2 - lat1) * r / 2) ** 2 + np.cos(lat1 * r) * np.cos(lat2 * r) * np.sin((lon2 - lon1) * r / 2) ** 2
    return 2 * EARTH_R * np.arcsin(np.sqrt(a))
