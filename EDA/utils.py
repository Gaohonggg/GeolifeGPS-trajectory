"""Hàm dùng chung cho các notebook EDA Geolife.

Mọi notebook đọc thẳng từ file .plt gốc và tính toán trong bộ nhớ, không lưu dữ liệu trung gian ra đĩa.
"""
from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "Geolife_Trajectories" / "Data"
PLT_COLS = ["lat", "lon", "zero", "alt_ft", "days", "date", "time"]
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


def _parse_user(user_dir: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Parse 1 user: các file .plt (bỏ 6 dòng header) + labels.txt; gán mode cho từng điểm."""
    user_dir = Path(user_dir)
    user = int(user_dir.name)
    frames, meta = [], []
    for plt_file in sorted((user_dir / "Trajectory").glob("*.plt")):
        df = pd.read_csv(plt_file, skiprows=6, header=None, names=PLT_COLS)
        meta.append({"user": user, "traj_id": plt_file.stem, "n_points": len(df),
                     "file_bytes": plt_file.stat().st_size})
        if df.empty:
            continue
        df["ts_utc"] = pd.to_datetime(df["date"] + " " + df["time"], format="%Y-%m-%d %H:%M:%S")
        df["traj_id"] = plt_file.stem
        frames.append(df[["traj_id", "lat", "lon", "alt_ft", "zero", "days", "ts_utc"]])
    pts = pd.concat(frames, ignore_index=True)
    pts.insert(0, "user", np.int16(user))

    lab_path = user_dir / "labels.txt"
    if lab_path.exists():
        lab = pd.read_csv(lab_path, sep="\t")
        lab.columns = ["start_utc", "end_utc", "mode"]
        lab["start_utc"] = pd.to_datetime(lab["start_utc"], format="%Y/%m/%d %H:%M:%S")
        lab["end_utc"] = pd.to_datetime(lab["end_utc"], format="%Y/%m/%d %H:%M:%S")
        lab.insert(0, "user", np.int16(user))
        # gán mode cho điểm: khoảng nhãn gần nhất bắt đầu trước điểm và chưa kết thúc
        pts = pts.sort_values("ts_utc", kind="stable")
        m = pd.merge_asof(pts[["ts_utc"]].reset_index(), lab.sort_values("start_utc")[["start_utc", "end_utc", "mode"]],
                          left_on="ts_utc", right_on="start_utc", direction="backward")
        ok = m["ts_utc"] <= m["end_utc"]
        pts["mode"] = pd.Series(np.where(ok, m["mode"], None), index=m["index"]).reindex(pts.index)
        pts = pts.sort_index()
    else:
        lab = pd.DataFrame(columns=["user", "start_utc", "end_utc", "mode"])
        pts["mode"] = None
    return pts, lab, pd.DataFrame(meta)


@lru_cache(maxsize=1)
def _load_raw() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    users = sorted(str(p) for p in RAW.iterdir() if p.is_dir())
    with ProcessPoolExecutor(max_workers=os.cpu_count()) as ex:
        results = list(ex.map(_parse_user, users))
    pts = pd.concat([r[0] for r in results], ignore_index=True)
    pts["mode"] = pts["mode"].astype("category")
    pts["traj_id"] = pts["traj_id"].astype("category")
    labels = pd.concat([r[1] for r in results if len(r[1])], ignore_index=True)
    files = pd.concat([r[2] for r in results], ignore_index=True)
    return pts, labels, files


def load_points(columns: list[str] | None = None) -> pd.DataFrame:
    """Toàn bộ điểm GPS, giữ nguyên thứ tự dòng như trong file gốc."""
    pts = _load_raw()[0]
    return (pts[columns] if columns else pts).copy()


def load_labels() -> pd.DataFrame:
    return _load_raw()[1].copy()


def load_files() -> pd.DataFrame:
    """Metadata từng file .plt: user, traj_id, n_points, file_bytes."""
    return _load_raw()[2].copy()


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


def add_geo(df: pd.DataFrame, grid_deg: float = 0.05) -> pd.DataFrame:
    """Thêm tz, utc_offset_h (có DST), ts_local, city, in_beijing theo toạ độ.

    Timezone tính trên lưới grid_deg rồi join về điểm cho nhanh. Điểm có toạ độ ngoài phạm vi nhận tz = "Unknown".
    """
    from timezonefinder import TimezoneFinder

    valid = df.lat.between(-90, 90) & df.lon.between(-180, 180)
    g_lat = (df.lat.where(valid, 0) / grid_deg).round().astype("int32")
    g_lon = (df.lon.where(valid, 0) / grid_deg).round().astype("int32")
    grid = pd.DataFrame({"g_lat": g_lat, "g_lon": g_lon})[valid.to_numpy()].drop_duplicates()
    glat, glon = grid.g_lat.to_numpy() * grid_deg, grid.g_lon.to_numpy() * grid_deg
    tf = TimezoneFinder()
    grid["tz"] = [tf.timezone_at(lat=a, lng=o) or "Unknown" for a, o in zip(glat, glon)]
    grid["city"] = nearest_city(glat, glon, max_km=80)
    key = pd.MultiIndex.from_arrays([g_lat, g_lon])
    grid = grid.set_index(["g_lat", "g_lon"])
    df["tz"] = pd.Categorical(np.where(valid, grid.tz.reindex(key).to_numpy(), "Unknown"))
    df["city"] = pd.Categorical(np.where(valid, grid.city.reindex(key).to_numpy(), "Other"))

    # UTC offset thật theo từng điểm (xét DST cho America/*, Europe/*...)
    offset_h = np.full(len(df), np.nan, dtype="float32")
    for tz, idx in df.groupby("tz", observed=True).indices.items():
        if tz == "Unknown":
            continue
        utc = df.ts_utc.iloc[idx].dt.tz_localize("UTC")
        local = utc.dt.tz_convert(tz).dt.tz_localize(None)
        offset_h[idx] = ((local - utc.dt.tz_localize(None)).dt.total_seconds() / 3600).to_numpy()
    df["utc_offset_h"] = offset_h
    df["ts_local"] = df.ts_utc + pd.to_timedelta(df.utc_offset_h.fillna(8), unit="h")
    df["in_beijing"] = in_beijing(df.lat.to_numpy(), df.lon.to_numpy())
    return df
