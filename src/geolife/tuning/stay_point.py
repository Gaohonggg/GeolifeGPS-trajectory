"""Phép đo tuning riêng của model stay_point (`docs/models/stay_point_v*.md`). Phép đo dùng chung: `tuning/common.py`."""
from __future__ import annotations

import pandas as pd

from ..evaluation import stay_metrics
from ..geo import haversine
from ..models.stay_point import detect_stays


def stay_grid(points, flags, Ds, Ts, max_gap_h, anchor="first") -> pd.DataFrame:
    """B2–B4: chỉ số stay cho mọi cặp (D, T), max_gap cố định."""
    rows = []
    for D in Ds:
        for T in Ts:
            st = detect_stays(points, D, T, max_gap_h, anchor)
            rows.append({"D_m": D, "T_min": T, **stay_metrics(st, points, flags)})
    return pd.DataFrame(rows)


def max_gap_table(points, flags, D_m, T_min, gaps_h, anchor="first") -> pd.DataFrame:
    """B5: chỉ số stay theo max_gap."""
    rows = [{"max_gap_h": g, **stay_metrics(detect_stays(points, D_m, T_min, g, anchor), points, flags)} for g in gaps_h]
    return pd.DataFrame(rows).set_index("max_gap_h")


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
