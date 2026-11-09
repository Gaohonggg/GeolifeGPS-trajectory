"""Phép đo tuning riêng của model dbscan (`docs/models/dbscan_v*.md`). Phép đo dùng chung: `tuning/common.py`."""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from ..evaluation import stay_metrics
from ..geo import haversine
from ..models.base import iter_users
from ..models.dbscan import cluster_users, detect_visits, grid_index, visits_from
from .common import pred_agreement


def cluster_extent(visits: pd.DataFrame, min_hours: float = 10.0) -> dict:
    """Kích thước của place (cụm) có tổng thời gian visit >= min_hours: khoảng cách xa nhất từ một visit tới tâm của place
    (tâm theo thời lượng visit, như `place_table`). Place quá rộng là dấu hiệu nối chuỗi."""
    w = visits.dur_h
    g = visits.assign(wl=visits.lat * w, wo=visits.lon * w).groupby(["user", "place"])
    c = g[["wl", "wo", "dur_h"]].sum()
    c = c[c.dur_h >= min_hours]
    j = visits.join(pd.DataFrame({"clat": c.wl / c.dur_h, "clon": c.wo / c.dur_h}), on=["user", "place"], how="inner")
    ext = j.assign(d=haversine(j.lat, j.lon, j.clat, j.clon)).groupby(["user", "place"]).d.max()
    return {"places_10h": len(ext), "extent_p50_m": round(float(ext.median()), 0), "extent_p95_m": round(float(ext.quantile(0.95)), 0),
            "wide_share": round(float((ext > 500).mean()), 4)}


def dbscan_grid(points, flags, p, eps_list, min_time_list) -> pd.DataFrame:
    """B2–B4: chỉ số visit và kích thước place cho mọi cặp (eps, min_time); các tham số khác lấy từ p."""
    rows = []
    for eps in eps_list:
        for mt in min_time_list:
            q = {**p, "eps_m": eps, "min_time_min": mt}
            v = visits_from(cluster_users(points, q), q)
            rows.append({"eps_m": eps, "min_time_min": mt, **stay_metrics(v, points, flags), **cluster_extent(v)})
    return pd.DataFrame(rows)


def visit_cut_table(points, flags, p, Ts, bridges) -> pd.DataFrame:
    """B5: chỉ số visit theo (T, bridge). Phân cụm chỉ chạy một lần vì không phụ thuộc hai tham số này."""
    cl = cluster_users(points, p)
    rows = [{"T_min": T, "bridge_min": b, **stay_metrics(visits_from(cl, {**p, "T_min": T, "bridge_min": b}), points, flags)}
            for T in Ts for b in bridges]
    return pd.DataFrame(rows)


def dbscan_max_gap_table(points, flags, p, gaps_h) -> pd.DataFrame:
    """B6: chỉ số visit theo max_gap (max_gap đổi trọng số thời gian nên phải phân cụm lại)."""
    rows = [{"max_gap_h": g, **stay_metrics(detect_visits(points, {**p, "max_gap_h": g}), points, flags)} for g in gaps_h]
    return pd.DataFrame(rows).set_index("max_gap_h")


def cell_table(model, points, flags, cells, ref_cell) -> pd.DataFrame:
    """B7: theo cell_m: số ô / user, thời gian phân cụm, chỉ số visit, và độ trùng home / office so với lưới mịn ref_cell."""
    users = np.unique(points.user)
    p0 = dict(model.params)
    res = {}
    for c in [ref_cell, *[c for c in cells if c != ref_cell]]:
        q = {**p0, "cell_m": c}
        t0 = time.perf_counter()
        v = visits_from(cluster_users(points, q), q)
        dt = time.perf_counter() - t0
        model.params = q
        _, _, pred = model.label(v, users)
        n = [len(np.unique(r * (1 << 32) + k)) for U in iter_users(points) for r, k in [grid_index(U.lat, U.lon, c)]]
        res[c] = ({"cell_m": c, "cells_per_user": int(np.median(n)), "cells_max": int(max(n)), "cluster_s": round(dt, 1),
                   **stay_metrics(v, points, flags)}, pred)
    model.params = p0
    rows = [{**r, **pred_agreement(res[ref_cell][1], pred, p0["same_place_m"])} for c, (r, pred) in sorted(res.items())]
    return pd.DataFrame(rows).set_index("cell_m")
