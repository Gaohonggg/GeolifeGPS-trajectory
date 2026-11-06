"""Phát hiện stay (Li et al., 2008) trên toàn chuỗi điểm của một user.

Stay = đoạn điểm liên tiếp, mọi điểm nằm trong bán kính D quanh điểm đầu, kéo dài >= T.
Chạy trên chuỗi đã ghép mọi file của user theo thời gian, không chạy riêng từng file: thời gian ở nhà / ở chỗ làm thường nằm
trong khoảng không ghi giữa hai file (EDA mục 6). Một khoảng không ghi dài hơn max_gap thì cắt stay: không ghi quá lâu
thì không còn biết user có ở yên hay không.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from numba import njit

from .geo import hav

STAY_COLS = ["user", "i0", "i1", "start_utc", "end_utc", "start_local", "end_local", "lat", "lon", "n_points", "dur_h", "tz"]


@njit(cache=True)
def _stay_points(lat, lon, t, D, T, max_gap):
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


@dataclass
class UserSeq:
    """Chuỗi điểm của một user dưới dạng mảng. ts, loc: giây kể từ epoch theo UTC và theo giờ local."""
    user: int
    lat: np.ndarray
    lon: np.ndarray
    ts: np.ndarray
    loc: np.ndarray
    tz: np.ndarray


def iter_users(points: pd.DataFrame):
    """points phải sort theo (user, ts_utc), như points.parquet."""
    ts = points.ts_utc.to_numpy().astype("datetime64[s]").astype(np.int64).astype(np.float64)
    loc = points.ts_local.to_numpy().astype("datetime64[s]").astype(np.int64).astype(np.float64)
    lat, lon, tz = points.lat.to_numpy(), points.lon.to_numpy(), points.tz.astype(str).to_numpy()
    for u, idx in points.groupby("user", sort=True).indices.items():
        yield UserSeq(int(u), lat[idx], lon[idx], ts[idx], loc[idx], tz[idx])


def detect_user(U: UserSeq, D_m: float, T_s: float, max_gap_s: float) -> pd.DataFrame:
    if len(U.ts) < 2:
        return pd.DataFrame(columns=STAY_COLS)
    s = np.array(_stay_points(U.lat, U.lon, U.ts, D_m, T_s, max_gap_s), dtype=np.int64).reshape(-1, 2)
    a, b = s[:, 0], s[:, 1]
    cs_a, cs_o = np.r_[0, np.cumsum(U.lat)], np.r_[0, np.cumsum(U.lon)]
    n = b - a + 1
    return pd.DataFrame({"user": U.user, "i0": a, "i1": b, "start_utc": U.ts[a], "end_utc": U.ts[b],
                         "start_local": U.loc[a], "end_local": U.loc[b],
                         "lat": (cs_a[b + 1] - cs_a[a]) / n, "lon": (cs_o[b + 1] - cs_o[a]) / n,
                         "n_points": n, "dur_h": (U.ts[b] - U.ts[a]) / 3600, "tz": U.tz[a]})


def detect_stays(points: pd.DataFrame, D_m: float, T_min: float, max_gap_h: float) -> pd.DataFrame:
    """Bảng stay của mọi user trong points. i0, i1 là chỉ số điểm trong chuỗi của user; thời gian tính bằng giây epoch."""
    out = [detect_user(U, D_m, T_min * 60, max_gap_h * 3600) for U in iter_users(points)]
    out = [o for o in out if len(o)]
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=STAY_COLS)
