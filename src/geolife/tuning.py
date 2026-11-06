"""Các phép đo dùng khi tuning tham số của model stay_point (B2–B8 trong `docs/models/stay_point_v*.md`).

Notebook `models/stay_point/v_<k>/tuning.ipynb` gọi các hàm này, nên mọi version được chọn tham số bằng đúng cùng một quy trình.
Mọi hàm chỉ nên chạy trên `dev`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .calendar import WorkCalendar
from .evaluation import stay_metrics
from .geo import haversine
from .home_office import hour_slices, pick_roles, place_table, role_slices
from .stays import detect_stays
from .timezone import tz_country

GAP_BINS = [1 / 6, 1, 3, 6, 12, 24, 48, 72, 168, 1e6]
GAP_LABELS = ["10'-1h", "1-3h", "3-6h", "6-12h", "12-24h", "24-48h", "48-72h", "3-7 ngày", "> 7 ngày"]


def stay_grid(points, flags, Ds, Ts, max_gap_h, anchor="first") -> pd.DataFrame:
    """B2–B4: chỉ số stay cho mọi cặp (D, T), max_gap cố định."""
    rows = []
    for D in Ds:
        for T in Ts:
            st = detect_stays(points, D, T, max_gap_h, anchor)
            rows.append({"D_m": D, "T_min": T, **stay_metrics(st, points, flags)})
    return pd.DataFrame(rows)


def gap_return_table(points, D_m) -> pd.DataFrame:
    """B5: với mọi cặp điểm liên tiếp của cùng user có khoảng không ghi >= 10 phút, % cặp mà điểm sau cách điểm trước <= D."""
    ts = points.ts_utc.to_numpy().astype("datetime64[s]").astype(np.int64)
    same_user = points.user.to_numpy()[1:] == points.user.to_numpy()[:-1]
    dt_h = np.diff(ts) / 3600
    lat, lon = points.lat.to_numpy(), points.lon.to_numpy()
    d = haversine(lat[:-1], lon[:-1], lat[1:], lon[1:])
    gp = pd.DataFrame({"dt_h": dt_h, "back": d <= D_m})[same_user & (dt_h >= 1 / 6)]
    gp["bin"] = pd.cut(gp.dt_h, GAP_BINS, labels=GAP_LABELS)
    return gp.groupby("bin", observed=True).agg(gaps=("back", "size"), back_share=("back", "mean"))


def max_gap_table(points, flags, D_m, T_min, gaps_h, anchor="first") -> pd.DataFrame:
    """B5: chỉ số stay theo max_gap."""
    rows = [{"max_gap_h": g, **stay_metrics(detect_stays(points, D_m, T_min, g, anchor), points, flags)} for g in gaps_h]
    return pd.DataFrame(rows).set_index("max_gap_h")


def window_coverage(stays) -> tuple[pd.DataFrame, dict]:
    """B6: % stay dài phủ từng giờ local (phủ >= 30 phút), tính theo user (user có >= 3 stay loại đó) rồi trung bình giữa các user.

    - Stay qua đêm: dài 6–24 giờ và có chứa 03:00 local.
    - Stay ban ngày của ngày làm việc: bắt đầu từ 06:00, kết thúc trước 22:00 cùng ngày, dài >= 3 giờ, rơi vào ngày làm việc.
    Trả về (bảng giờ × loại stay, {loại: (số stay, số user)}).
    """
    cal = WorkCalendar(np.unique(tz_country(stays.tz.unique())), range(2006, 2014))
    vid, h, hb = hour_slices(stays.start_local.to_numpy(), stays.end_local.to_numpy())
    sl = pd.DataFrame({"vid": vid, "user": stays.user.to_numpy()[vid], "hour": (hb % 24).astype(int), "h": h})
    sday = np.floor(stays.start_local / 86400).astype(np.int64)
    eday = np.floor(stays.end_local / 86400).astype(np.int64)
    sh, eh = (stays.start_local % 86400) / 3600, (stays.end_local % 86400) / 3600
    overnight = stays.index.isin(sl.vid[sl.hour == 3].unique()) & stays.dur_h.between(6, 24)
    daytime = ((sday == eday) & (sh >= 6) & (eh <= 22) & (stays.dur_h >= 3)
               & cal.is_workday(tz_country(stays.tz.to_numpy()), sday.to_numpy())).to_numpy()
    cov, counts = {}, {}
    for name, mask in [("qua đêm", np.asarray(overnight)), ("ban ngày, ngày làm việc", daytime)]:
        s = sl[np.isin(sl.vid, np.flatnonzero(mask)) & (sl.h >= 0.5)]
        c = s.groupby(["user", "hour"]).vid.nunique().unstack(fill_value=0).reindex(columns=range(24), fill_value=0)
        n = stays[mask].groupby("user").size().reindex(c.index)
        cov[name] = c.div(n, axis=0)[n >= 3].mean()
        counts[name] = (int(mask.sum()), int((n >= 3).sum()))
    return pd.DataFrame(cov), counts


def hours_to_window(hours: list[int]) -> list[int]:
    """Danh sách giờ liên tiếp (có thể vắt qua nửa đêm) → [giờ đầu, giờ cuối + 1) như trong config."""
    hs = set(hours)
    start = next(h for h in hours if (h - 1) % 24 not in hs)
    end = next(h for h in hours if (h + 1) % 24 not in hs)
    return [start, (end + 1) % 24]


def place_eps_table(model, stays, users, eps_list, same_m=200.0) -> pd.DataFrame:
    """B7: theo place_eps: số place / user, số user có home / office, % user có home / office dịch > same_m so với eps liền trước."""
    old = model.params["place_eps_m"]
    prev, rows = None, []
    for eps in eps_list:
        model.params["place_eps_m"] = eps
        _, places, pred = model.label(stays, users)
        p = pred.set_index(["user", "role"])
        r = {"eps_m": eps, "places_per_user": places.groupby("user").size().median(),
             "home_found": int(p.xs("home", level="role").lat.notna().sum()),
             "office_found": int(p.xs("office", level="role").lat.notna().sum())}
        if prev is not None:
            j = p.join(prev.add_suffix("_prev")).dropna(subset=["lat", "lat_prev"])
            moved = haversine(j.lat, j.lon, j.lat_prev, j.lon_prev) > same_m
            for role in ["home", "office"]:
                r[f"{role}_moved_vs_prev"] = moved[j.index.get_level_values("role") == role].mean()
        rows.append(r)
        prev = p[["lat", "lon"]]
    model.params["place_eps_m"] = old
    return pd.DataFrame(rows).set_index("eps_m")


def min_days_agreement(model, stays, users, ks=(1, 2, 3, 5, 10), reps=30, min_days=20, seed=0) -> pd.DataFrame:
    """B8: với user có >= min_days đêm (ngày làm việc) ở home (office), rút ngẫu nhiên k ngày, chọn lại home / office chỉ từ
    giờ trong k ngày đó, đo % lần trùng với kết quả dùng toàn bộ dữ liệu (cùng place). Trả về bảng theo (role, user, k)."""
    p = model.params
    st, _, _ = model.label(stays, users)
    cal = WorkCalendar(np.unique(tz_country(st.tz.unique())), range(2006, 2014))
    rs = role_slices(st, cal, tuple(p["night_hours"]), tuple(p["work_hours"]))
    ptab = place_table(st, rs)
    full = pick_roles(ptab, users, 1, 1, p["same_place_m"]).set_index(["user", "role"])
    # office không được rơi vào vùng quanh home (như trong model): bỏ trước các place cách home <= same_place_m
    hm = full.xs("home", level="role")[["lat", "lon"]].rename(columns={"lat": "hlat", "lon": "hlon"})
    pj = ptab.join(hm, on="user")
    near = pj.loc[haversine(pj.lat, pj.lon, pj.hlat, pj.hlon) <= p["same_place_m"], ["user", "place"]]
    near_home = set(map(tuple, near.to_numpy()))
    rng = np.random.default_rng(seed)
    rows = []
    for role, dcol in [("home", "night_day"), ("office", "day")]:
        r = rs[rs[role]]
        if role == "office":
            r = r[[(a, b) not in near_home for a, b in zip(r.user, r.place)]]
        for u, g in r.groupby("user"):
            ref = full.loc[(u, role), "place"]
            days = g[dcol].unique()
            if ref < 0 or len(days) < min_days:
                continue
            for k in ks:
                hit = 0
                for _ in range(reps):
                    sub = g[g[dcol].isin(rng.choice(days, k, replace=False))]
                    hit += sub.groupby("place").h.sum().idxmax() == ref
                rows.append({"role": role, "user": u, "k": k, "match": hit / reps})
    return pd.DataFrame(rows)
