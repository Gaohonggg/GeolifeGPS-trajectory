"""DBSCAN: GPS → visit (cụm DBSCAN trên ô lưới, trọng số thời gian) → home / office. Mỗi cụm là một place, nên không có bước
gom place riêng. Cách chọn toạ độ đại diện của ô lấy từ config (`cell_center`).

**Phát hiện visit** (`detect_visits`). Cho từng user, trên chuỗi đã ghép mọi file theo thời gian (như stay_point):
1. **Trọng số thời gian:** mỗi điểm nặng bằng số giây tới điểm kế tiếp, w = t[i+1] - t[i]. Khoảng không ghi dài hơn max_gap
   thì w = 0: không ghi quá lâu thì không biết user ở đâu (cùng quy tắc với stay_point). Mật độ vì vậy là **thời gian lưu lại**,
   không phụ thuộc thiết bị ghi 1 giây hay 5 giây một điểm.
2. **Gộp vào ô lưới** cạnh `cell_m`: cộng trọng số các điểm trong ô. DBSCAN chạy trên ô chứ không trên điểm, vì một vùng nhà có
   hàng trăm nghìn điểm sẽ làm danh sách láng giềng quá lớn. Toạ độ đại diện của ô (`cell_center`):
   - `"grid"`: tâm hình học của ô;
   - `"weighted"`: trung bình có trọng số thời gian của các điểm trong ô, Σ(w·lat)/Σw, Σ(w·lon)/Σw.
3. **DBSCAN có trọng số** trên các ô (khoảng cách haversine): ô là lõi khi tổng thời gian trong bán kính `eps_m` quanh nó
   >= `min_time`. Mỗi cụm là một **place**; ô không thuộc cụm nào là nhiễu.
4. **Cắt thành visit theo thời gian:** mỗi điểm nhận nhãn của ô chứa nó. Duyệt chuỗi điểm: đoạn liên tiếp cùng cụm là một visit.
   Đoạn nhiễu chen giữa ngắn hơn `bridge` được nối vào visit; quay lại cùng cụm sau đó thì visit tiếp tục. Gặp cụm khác, nhiễu
   kéo dài hơn `bridge`, hoặc khoảng không ghi dài hơn max_gap thì visit kết thúc. Chỉ giữ visit dài >= T.

Output có đúng các cột của bảng stay (`base.STAY_COLS`) cộng cột `place` (mã cụm theo từng user), nên mọi bước sau
(home / office, confidence, chỉ số) dùng lại được. Toạ độ của visit là trung bình có trọng số thời gian của các điểm thuộc cụm
trong visit, ở cả hai cách chọn `cell_center`.

**Home / office**: `home_office.label_roles`, dùng chung cho mọi model.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from numba import njit
from sklearn.cluster import DBSCAN

from ..geo import EARTH_R
from ..home_office import label_roles
from .base import STAY_COLS, Model, UserSeq, iter_users

VISIT_COLS = STAY_COLS + ["place"]
_M_PER_DEG = EARTH_R * np.pi / 180


def time_weights(ts: np.ndarray, max_gap_s: float) -> np.ndarray:
    """Số giây mỗi điểm đại diện: tới điểm kế tiếp, = 0 nếu khoảng đó > max_gap; điểm cuối = 0."""
    dt = np.diff(ts, append=ts[-1])
    return np.where(dt <= max_gap_s, dt, 0.0)


def grid_index(lat: np.ndarray, lon: np.ndarray, cell_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Hàng / cột của ô chứa mỗi điểm. Hàng cách nhau cell_m theo vĩ độ; bề ngang ô trong mỗi hàng được nới theo cos(vĩ độ)
    để ô luôn rộng cell_m mét."""
    dlat = cell_m / _M_PER_DEG
    row = np.floor(lat / dlat).astype(np.int64)
    dlon = dlat / np.cos(np.radians((row + 0.5) * dlat))
    col = np.floor(lon / dlon).astype(np.int64)
    return row, col


def _cell_center_grid(row, col, lat, lon, w, inv, n_cells, cell_m):
    dlat = cell_m / _M_PER_DEG
    r = np.zeros(n_cells, np.int64)
    c = np.zeros(n_cells, np.int64)
    r[inv], c[inv] = row, col
    clat = (r + 0.5) * dlat
    return clat, (c + 0.5) * dlat / np.cos(np.radians(clat))


def _cell_center_weighted(row, col, lat, lon, w, inv, n_cells, cell_m):
    sw = np.bincount(inv, w, n_cells)
    # ô chỉ gồm điểm có w = 0 (ngay trước một khoảng không ghi dài): dùng trung bình thường của các điểm
    n = np.bincount(inv, minlength=n_cells)
    has_w = sw > 0
    clat = np.where(has_w, np.bincount(inv, w * lat, n_cells) / np.where(has_w, sw, 1), np.bincount(inv, lat, n_cells) / n)
    clon = np.where(has_w, np.bincount(inv, w * lon, n_cells) / np.where(has_w, sw, 1), np.bincount(inv, lon, n_cells) / n)
    return clat, clon


CELL_CENTERS = {"grid": _cell_center_grid, "weighted": _cell_center_weighted}


def _cell_center_fn(cell_center: str):
    if cell_center not in CELL_CENTERS:
        raise ValueError(f"cell_center phải là một trong {sorted(CELL_CENTERS)}, nhận được {cell_center!r}")
    return CELL_CENTERS[cell_center]


def cluster_points(U: UserSeq, w: np.ndarray, cell_m: float, cell_center: str, eps_m: float, min_time_s: float) -> np.ndarray:
    """Nhãn cụm của từng điểm (-1 = nhiễu)."""
    row, col = grid_index(U.lat, U.lon, cell_m)
    key = row * (1 << 32) + (col + (1 << 31))
    _, inv = np.unique(key, return_inverse=True)
    n_cells = int(inv.max()) + 1
    clat, clon = _cell_center_fn(cell_center)(row, col, U.lat, U.lon, w, inv, n_cells, cell_m)
    cw = np.bincount(inv, w, n_cells)
    db = DBSCAN(eps=eps_m / EARTH_R, min_samples=min_time_s, metric="haversine", algorithm="ball_tree")
    lab = db.fit_predict(np.radians(np.c_[clat, clon]), sample_weight=cw)
    return lab[inv]


@njit(cache=True)
def _visits(lab, t, T, bridge, max_gap):
    """Các visit (i0, i1, cụm) trên chuỗi nhãn của điểm. i0, i1 là điểm đầu / cuối thuộc cụm."""
    out = []
    n = len(lab)
    c, i0, last = -1, -1, -1
    for j in range(n):
        if c >= 0 and j > 0 and t[j] - t[j - 1] > max_gap:
            if t[last] - t[i0] >= T:
                out.append((i0, last, c))
            c = -1
        if lab[j] < 0:
            if c >= 0 and t[j] - t[last] > bridge:
                if t[last] - t[i0] >= T:
                    out.append((i0, last, c))
                c = -1
        elif lab[j] == c:
            last = j
        else:
            if c >= 0 and t[last] - t[i0] >= T:
                out.append((i0, last, c))
            c, i0, last = lab[j], j, j
    if c >= 0 and t[last] - t[i0] >= T:
        out.append((i0, last, c))
    return out


def cluster_users(points: pd.DataFrame, p: dict) -> list[tuple[UserSeq, np.ndarray, np.ndarray]]:
    """Bước 1–3 cho mọi user: (chuỗi điểm, trọng số thời gian, nhãn cụm của từng điểm). Chỉ phụ thuộc cell_m, cell_center,
    eps_m, min_time_min, max_gap_h; tuning tính một lần rồi thử nhiều T / bridge trên cùng nhãn."""
    _cell_center_fn(p["cell_center"])
    out = []
    for U in iter_users(points):
        if len(U.ts) < 2:
            continue
        w = time_weights(U.ts, p["max_gap_h"] * 3600)
        out.append((U, w, cluster_points(U, w, p["cell_m"], p["cell_center"], p["eps_m"], p["min_time_min"] * 60)))
    return out


def user_visits(U: UserSeq, w: np.ndarray, lab: np.ndarray, p: dict) -> pd.DataFrame:
    """Bước 4 cho một user."""
    v = np.array(_visits(lab, U.ts, p["T_min"] * 60, p["bridge_min"] * 60, p["max_gap_h"] * 3600),
                 dtype=np.int64).reshape(-1, 3)
    a, b, c = v[:, 0], v[:, 1], v[:, 2]
    # Toạ độ visit: trung bình có trọng số thời gian của các điểm thuộc cụm của visit, nằm trong [a, b]
    lat, lon = np.empty(len(v)), np.empty(len(v))
    for k in range(len(v)):
        sl = slice(a[k], b[k] + 1)
        m = lab[sl] == c[k]
        ww = w[sl][m]
        ww = ww if ww.sum() > 0 else np.ones(m.sum())
        lat[k], lon[k] = np.average(U.lat[sl][m], weights=ww), np.average(U.lon[sl][m], weights=ww)
    return pd.DataFrame({"user": U.user, "i0": a, "i1": b, "start_utc": U.ts[a], "end_utc": U.ts[b],
                         "start_local": U.loc[a], "end_local": U.loc[b], "lat": lat, "lon": lon,
                         "n_points": b - a + 1, "dur_h": (U.ts[b] - U.ts[a]) / 3600, "tz": U.tz[a], "place": c})


def visits_from(clustered, p: dict) -> pd.DataFrame:
    out = [user_visits(U, w, lab, p) for U, w, lab in clustered]
    out = [o for o in out if len(o)]
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=VISIT_COLS)


def detect_visits(points: pd.DataFrame, p: dict) -> pd.DataFrame:
    """Bảng visit của mọi user. p: params của model dbscan (cell_m, cell_center, eps_m, min_time_min, T_min, bridge_min,
    max_gap_h). Cột như bảng stay, thêm `place`."""
    return visits_from(cluster_users(points, p), p)


# ---------------------------------------------------------------- model


class DbscanModel(Model):
    name = "dbscan"

    def stays(self, points: pd.DataFrame) -> pd.DataFrame:
        """Bảng visit, cùng cột với bảng stay của stay_point, có sẵn cột place."""
        return detect_visits(points, self.params)

    def label(self, stays: pd.DataFrame, users) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """visits → (visits, bảng place, dự đoán). Dự đoán luôn có confidence (`confidence.add_confidence`)."""
        places, pred = label_roles(stays, users, self.params)
        return stays, places, pred

    def predict(self, points: pd.DataFrame):
        stays, _, pred = self.label(self.stays(points), np.unique(points.user))
        return stays, pred
