"""Stay-point: GPS → stay → place → home / office.

**Bước 1 — stay** (`detect_stays`). Stay = đoạn điểm liên tiếp kéo dài >= T, mọi điểm nằm trong bán kính D quanh **neo**. Có hai
cách đặt neo (`anchor` trong config, mặc định "first"):
- `"first"` (Li et al., 2008): neo là điểm đầu của stay, cố định.
- `"centroid"`: neo động, là tâm (trung bình lat, lon, mỗi điểm nặng như nhau) của các điểm đã nhận vào stay; tính lại sau mỗi
  điểm được nhận. Điểm mới được nhận khi cách tâm hiện tại <= D. Thời gian không đổi: stay vẫn bắt đầu ở điểm đầu và T đo từ đó.
Chạy trên chuỗi đã ghép mọi file của user theo thời gian, không chạy riêng từng file: thời gian ở nhà / ở chỗ làm thường nằm
trong khoảng không ghi giữa hai file (EDA mục 6). Một khoảng không ghi dài hơn max_gap thì cắt stay: không ghi quá lâu
thì không còn biết user có ở yên hay không.

**Bước 2 — place** (`assign_places`). Gom các stay của một user thành place (địa điểm): duyệt stay theo thời lượng giảm dần;
stay chưa thuộc place nào trở thành tâm của place mới và kéo theo mọi stay chưa gán nằm trong bán kính eps quanh nó. Khác DBSCAN
(min_samples = 1) ở chỗ place không thể "nối chuỗi" dài vô hạn: mọi stay của place nằm trong eps quanh tâm, nên toạ độ của
place không bị kéo vào giữa hai nơi khác nhau.

**Bước 3 — home / office**: `home_office.label_roles`, dùng chung cho mọi model.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from numba import njit
from sklearn.neighbors import BallTree

from ..geo import EARTH_R, hav
from ..home_office import label_roles
from .base import STAY_COLS, Model, UserSeq, iter_users

# ---------------------------------------------------------------- bước 1: stay


@njit(cache=True)
def _stays_first_anchor(lat, lon, t, D, T, max_gap):
    n = len(lat)
    out = []
    i = 0
    while i < n:
        j = i + 1
        while j < n and t[j] - t[j - 1] <= max_gap and hav(lat[i], lon[i], lat[j], lon[j]) <= D:
            j += 1
        if t[j - 1] - t[i] >= T:
            out.append((i, j - 1))
            i = j
        else:
            i += 1
    return out


@njit(cache=True)
def _stays_centroid_anchor(lat, lon, t, D, T, max_gap):
    n = len(lat)
    out = []
    i = 0
    while i < n:
        s_lat, s_lon, k = lat[i], lon[i], 1
        j = i + 1
        while j < n and t[j] - t[j - 1] <= max_gap and hav(s_lat / k, s_lon / k, lat[j], lon[j]) <= D:
            s_lat += lat[j]
            s_lon += lon[j]
            k += 1
            j += 1
        if t[j - 1] - t[i] >= T:
            out.append((i, j - 1))
            i = j
        else:
            i += 1
    return out


ANCHORS = {"first": _stays_first_anchor, "centroid": _stays_centroid_anchor}


def _anchor_fn(anchor: str):
    if anchor not in ANCHORS:
        raise ValueError(f"anchor phải là một trong {sorted(ANCHORS)}, nhận được {anchor!r}")
    return ANCHORS[anchor]


def detect_user(U: UserSeq, D_m: float, T_s: float, max_gap_s: float, anchor: str = "first") -> pd.DataFrame:
    fn = _anchor_fn(anchor)
    if len(U.ts) < 2:
        return pd.DataFrame(columns=STAY_COLS)
    s = np.array(fn(U.lat, U.lon, U.ts, D_m, T_s, max_gap_s), dtype=np.int64).reshape(-1, 2)
    a, b = s[:, 0], s[:, 1]
    cs_a, cs_o = np.r_[0, np.cumsum(U.lat)], np.r_[0, np.cumsum(U.lon)]
    n = b - a + 1
    return pd.DataFrame({"user": U.user, "i0": a, "i1": b, "start_utc": U.ts[a], "end_utc": U.ts[b],
                         "start_local": U.loc[a], "end_local": U.loc[b],
                         "lat": (cs_a[b + 1] - cs_a[a]) / n, "lon": (cs_o[b + 1] - cs_o[a]) / n,
                         "n_points": n, "dur_h": (U.ts[b] - U.ts[a]) / 3600, "tz": U.tz[a]})


def detect_stays(points: pd.DataFrame, D_m: float, T_min: float, max_gap_h: float, anchor: str = "first") -> pd.DataFrame:
    """Bảng stay của mọi user trong points. i0, i1 là chỉ số điểm trong chuỗi của user; thời gian tính bằng giây epoch.
    Toạ độ của stay là trung bình các điểm của nó (với anchor="centroid" thì trùng neo cuối cùng)."""
    _anchor_fn(anchor)
    out = [detect_user(U, D_m, T_min * 60, max_gap_h * 3600, anchor) for U in iter_users(points)]
    out = [o for o in out if len(o)]
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=STAY_COLS)


# ---------------------------------------------------------------- bước 2: place


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


# ---------------------------------------------------------------- model


class StayPointModel(Model):
    name = "stay_point"

    def stays(self, points: pd.DataFrame) -> pd.DataFrame:
        p = self.params
        return detect_stays(points, p["D_m"], p["T_min"], p["max_gap_h"], p.get("anchor", "first"))

    def label(self, stays: pd.DataFrame, users) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """stays → (stays có cột place, bảng place, dự đoán). Dự đoán luôn có confidence (`confidence.add_confidence`)."""
        stays = stays.assign(place=assign_places(stays, self.params["place_eps_m"]).to_numpy())
        places, pred = label_roles(stays, users, self.params)
        return stays, places, pred

    def predict(self, points: pd.DataFrame):
        stays, _, pred = self.label(self.stays(points), np.unique(points.user))
        return stays, pred
