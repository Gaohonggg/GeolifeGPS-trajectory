"""Confidence cho từng dự đoán home / office, tính bằng bootstrap theo khối thời gian.

Với mỗi user:
1. Gom các lát giờ (`home_office.role_slices`) theo khối thời gian (`block`: tuần hoặc ngày). Mỗi khối có số giờ và số đêm
   (home) / số ngày làm việc (office) ở từng place. Home lấy khối theo đêm (`night_day`), office theo ngày (`day`).
2. Lấy mẫu lại các khối có hoàn lại, `n_boot` lần. Mỗi lần mẫu là một hàng của ma trận W (số lần mỗi khối được bốc), nên giờ và
   số ngày của mọi place trong mọi lần mẫu là một phép nhân ma trận. Khối được bốc lặp lại thì số đêm / ngày của nó cộng lặp lại.
3. Mỗi lần mẫu chọn lại home / office theo đúng luật của `pick_roles`: đủ `min_nights` / `min_workdays`, office cách home của
   chính lần mẫu đó hơn `same_place_m`, lấy place nhiều giờ nhất.
4. `confidence` = tỉ lệ lần mẫu chọn đúng place đã dự đoán. Dự đoán bị abstain thì confidence = null.

Hai cột chẩn đoán, tính trên toàn bộ dữ liệu, không gộp vào confidence:
- `regularity`: số đêm (ngày làm việc) ở place được chọn / số đêm (ngày làm việc) user có dữ liệu trong khung giờ đó.
- `margin`: (giờ place thứ nhất - giờ place thứ hai) / giờ place thứ nhất, trong các place đủ điều kiện; chỉ có một place thì = 1.

Mỗi user có bộ sinh số ngẫu nhiên riêng (seed, user), nên confidence của một user không phụ thuộc user nào khác được chạy cùng.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .geo import haversine

CONF_COLS = ["confidence", "regularity", "margin"]
# 1970-01-01 là thứ Năm: cộng 3 để tuần bắt đầu từ thứ Hai
_BLOCKS = {"week": lambda d: (d + 3) // 7, "day": lambda d: d}


def block_table(slices: pd.DataFrame, block: str = "week") -> pd.DataFrame:
    """Một dòng mỗi (user, role, block, place): giờ và số đêm / ngày làm việc khác nhau trong khối."""
    if block not in _BLOCKS:
        raise ValueError(f"block phải là một trong {sorted(_BLOCKS)}, nhận được {block!r}")
    out = []
    for role, dcol in [("home", "night_day"), ("office", "day")]:
        s = slices[slices[role]]
        t = (s.assign(block=_BLOCKS[block](s[dcol].to_numpy()))
             .groupby(["user", "block", "place"]).agg(h=("h", "sum"), days=(dcol, "nunique")).reset_index())
        out.append(t.assign(role=role))
    return pd.concat(out, ignore_index=True)


def _dense(t: pd.DataFrame, blocks: np.ndarray, places: np.ndarray):
    """Bảng dài (block, place, h, days) → hai ma trận khối × place."""
    H = np.zeros((len(blocks), len(places)))
    Dy = np.zeros((len(blocks), len(places)))
    bi, pi = np.searchsorted(blocks, t.block.to_numpy()), np.searchsorted(places, t.place.to_numpy())
    H[bi, pi], Dy[bi, pi] = t.h.to_numpy(), t.days.to_numpy()
    return H, Dy


def _winner(hours: np.ndarray, ok: np.ndarray) -> np.ndarray:
    """Chỉ số cột thắng của từng hàng (giờ nhiều nhất trong các cột ok; hoà thì cột đầu, như idxmax), -1 khi không có cột ok."""
    score = np.where(ok, hours, -np.inf)
    w = score.argmax(axis=1)
    return np.where(ok.any(axis=1), w, -1)


def _margin(hours: np.ndarray, ok: np.ndarray) -> float:
    h = np.sort(hours[ok])[::-1]
    if len(h) == 0:
        return np.nan
    return 1.0 if len(h) == 1 else float((h[0] - h[1]) / h[0])


def _user_conf(t: pd.DataFrame, plc: pd.DataFrame, ref: dict, rules: dict, n_boot: int, rng) -> dict:
    """t: bảng khối của một user; plc: bảng place của user (place, lat, lon); ref: place đã dự đoán theo role (-1 = abstain)."""
    blocks = np.unique(t.block.to_numpy())
    places = plc.place.to_numpy()
    Hh, Dh = _dense(t[t.role == "home"], blocks, places)
    Ho, Do = _dense(t[t.role == "office"], blocks, places)
    near = haversine(plc.lat.to_numpy()[:, None], plc.lon.to_numpy()[:, None],
                     plc.lat.to_numpy()[None, :], plc.lon.to_numpy()[None, :]) <= rules["same_place_m"]

    n = len(blocks)
    W = rng.multinomial(n, np.full(n, 1 / n), size=n_boot).astype(np.float64)
    home_h, home_d = W @ Hh, W @ Dh
    home = _winner(home_h, (home_h > 0) & (home_d >= rules["min_nights"]))
    off_h, off_d = W @ Ho, W @ Do
    # office không được cách home của chính lần mẫu đó <= same_place_m; lần mẫu không có home thì không loại gì
    excl = np.where((home >= 0)[:, None], near[np.maximum(home, 0)], False)
    office = _winner(off_h, (off_h > 0) & (off_d >= rules["min_workdays"]) & ~excl)

    out = {}
    for role, win, H, Dy, need in [("home", home, Hh, Dh, rules["min_nights"]),
                                   ("office", office, Ho, Do, rules["min_workdays"])]:
        r = ref.get(role, -1)
        if r < 0:
            out[role] = (np.nan, np.nan, np.nan)
            continue
        col = int(np.searchsorted(places, r))
        h, d = H.sum(0), Dy.sum(0)
        ok = (h > 0) & (d >= need)
        if role == "office" and ref.get("home", -1) >= 0:
            ok &= ~near[int(np.searchsorted(places, ref["home"]))]
        out[role] = (float((win == col).mean()), d[col], _margin(h, ok))
    return out


def add_confidence(pred: pd.DataFrame, places: pd.DataFrame, slices: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Thêm các cột CONF_COLS vào bảng dự đoán của `pick_roles`. params: params của model (có khối `confidence`)."""
    cp = params["confidence"]
    tab = block_table(slices, cp["block"])
    # Mẫu số của regularity: số đêm / ngày làm việc khác nhau user có dữ liệu trong khung giờ, ở bất kỳ place nào
    seen = {"home": slices[slices.home].groupby("user").night_day.nunique(),
            "office": slices[slices.office].groupby("user").day.nunique()}
    ref = {(u, r): int(p) for u, r, p in zip(pred.user, pred.role, pred.place)}
    T, PL = dict(tuple(tab.groupby("user"))), dict(tuple(places.groupby("user")))
    vals = {}
    for u in np.unique(pred.user):
        if u not in T:
            continue
        uref = {r: ref.get((u, r), -1) for r in ("home", "office")}
        if max(uref.values()) < 0:
            continue
        plc = PL[u].sort_values("place")
        res = _user_conf(T[u], plc, uref, params, cp["n_boot"], np.random.default_rng([cp["seed"], int(u)]))
        for role, (c, days, m) in res.items():
            if not np.isnan(c):
                vals[(u, role)] = (c, days / seen[role].get(u, np.nan), m)
    v = pd.DataFrame([(u, r, *x) for (u, r), x in vals.items()], columns=["user", "role", *CONF_COLS])
    return pred.drop(columns=[c for c in CONF_COLS if c in pred], errors="ignore").merge(v, on=["user", "role"], how="left")
