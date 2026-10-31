"""Hàm dùng chung cho các notebook EDA Geolife."""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
FIG_DIR = ROOT / "EDA" / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

EARTH_R = 6_371_008.8  # m

# Bounding box nội thành + ngoại ô Bắc Kinh (xấp xỉ vành đai 6 mở rộng)
BEIJING_BBOX = dict(lat_min=39.6, lat_max=40.3, lon_min=115.9, lon_max=116.8)

# Một số thành phố tham chiếu để gán tên khu vực (nearest city)
CITIES = {
    "Beijing": (39.904, 116.407), "Tianjin": (39.084, 117.201), "Shanghai": (31.230, 121.474),
    "Hangzhou": (30.274, 120.155), "Nanjing": (32.060, 118.797), "Suzhou": (31.299, 120.585),
    "Guangzhou": (23.129, 113.264), "Shenzhen": (22.543, 114.058), "Hong Kong": (22.320, 114.170),
    "Qingdao": (36.067, 120.383), "Dalian": (38.914, 121.615), "Shenyang": (41.806, 123.432),
    "Harbin": (45.803, 126.535), "Changchun": (43.817, 125.324), "Jinan": (36.651, 117.120),
    "Shijiazhuang": (38.042, 114.515), "Taiyuan": (37.871, 112.549), "Hohhot": (40.842, 111.749),
    "Zhangjiakou": (40.768, 114.886), "Chengde": (40.952, 117.963), "Qinhuangdao": (39.935, 119.600),
    "Baoding": (38.874, 115.465), "Tangshan": (39.630, 118.180), "Zhengzhou": (34.746, 113.625),
    "Xi'an": (34.341, 108.940), "Wuhan": (30.593, 114.305), "Changsha": (28.228, 112.939),
    "Chengdu": (30.573, 104.066), "Chongqing": (29.563, 106.551), "Kunming": (25.038, 102.718),
    "Guilin": (25.274, 110.290), "Xiamen": (24.480, 118.089), "Fuzhou": (26.074, 119.296),
    "Sanya": (18.252, 109.512), "Haikou": (20.044, 110.199), "Lhasa": (29.652, 91.172),
    "Urumqi": (43.825, 87.617), "Lanzhou": (36.061, 103.834), "Xining": (36.617, 101.778),
    "Yinchuan": (38.487, 106.231), "Taipei": (25.033, 121.565), "Seoul": (37.566, 126.978),
    "Tokyo": (35.676, 139.650), "Osaka": (34.694, 135.502), "Singapore": (1.352, 103.820),
    "Bangkok": (13.756, 100.502), "Seattle": (47.606, -122.332), "Redmond": (47.674, -122.121),
    "San Francisco": (37.775, -122.419), "Los Angeles": (34.052, -118.244), "New York": (40.713, -74.006),
    "Boston": (42.360, -71.059), "Chicago": (41.878, -87.630), "Vancouver": (49.283, -123.121),
    "London": (51.507, -0.128), "Paris": (48.857, 2.352), "Berlin": (52.520, 13.405),
    "Moscow": (55.756, 37.617), "Sydney": (-33.869, 151.209), "Dubai": (25.205, 55.271),
}


def setup_style() -> None:
    sns.set_theme(style="whitegrid", context="notebook")
    plt.rcParams.update({"figure.figsize": (11, 4.5), "figure.dpi": 100, "axes.titleweight": "bold"})
    pd.set_option("display.max_columns", 50)
    pd.set_option("display.width", 200)
    pd.set_option("display.float_format", lambda x: f"{x:,.4f}")


def savefig(name: str) -> None:
    plt.savefig(FIG_DIR / f"{name}.png", bbox_inches="tight", dpi=110)


def load_points(columns: list[str] | None = None) -> pd.DataFrame:
    return pd.read_parquet(PROCESSED / "points.parquet", columns=columns)


def load_labels() -> pd.DataFrame:
    return pd.read_parquet(PROCESSED / "labels.parquet")


def load_files() -> pd.DataFrame:
    return pd.read_parquet(PROCESSED / "files.parquet")


def haversine(lat1, lon1, lat2, lon2):
    """Khoảng cách (m) giữa 2 mảng toạ độ (độ)."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_R * np.arcsin(np.sqrt(a))


def add_kinematics(df: pd.DataFrame, group: str = "traj_key") -> pd.DataFrame:
    """Thêm dt_s, dist_m, speed_kmh giữa điểm liên tiếp (trong cùng group). df phải đã sort."""
    same = df[group].to_numpy()[1:] == df[group].to_numpy()[:-1]
    lat, lon = df["lat"].to_numpy(), df["lon"].to_numpy()
    ts = df["ts_utc"].to_numpy().astype("datetime64[ns]").astype(np.int64) / 1e9
    dt = np.full(len(df), np.nan)
    dist = np.full(len(df), np.nan)
    dt[1:] = np.where(same, ts[1:] - ts[:-1], np.nan)
    dist[1:] = np.where(same, haversine(lat[:-1], lon[:-1], lat[1:], lon[1:]), np.nan)
    df["dt_s"] = dt
    df["dist_m"] = dist
    with np.errstate(divide="ignore", invalid="ignore"):
        df["speed_kmh"] = np.where(dt > 0, dist / dt * 3.6, np.nan)
    return df


def nearest_city(lat: np.ndarray, lon: np.ndarray, max_km: float = 80.0) -> np.ndarray:
    names = np.array(list(CITIES))
    clat = np.array([v[0] for v in CITIES.values()])
    clon = np.array([v[1] for v in CITIES.values()])
    d = haversine(lat[:, None], lon[:, None], clat[None, :], clon[None, :]) / 1000
    idx = d.argmin(axis=1)
    return np.where(d[np.arange(len(lat)), idx] <= max_km, names[idx], "Other")


def in_beijing(lat, lon) -> np.ndarray:
    b = BEIJING_BBOX
    return (lat >= b["lat_min"]) & (lat <= b["lat_max"]) & (lon >= b["lon_min"]) & (lon <= b["lon_max"])
