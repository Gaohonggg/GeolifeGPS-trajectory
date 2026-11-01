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


CHINA_TZ = ["Asia/Shanghai", "Asia/Urumqi", "Asia/Chongqing", "Asia/Harbin", "Asia/Kashgar"]


def lookup_tz(lat: np.ndarray, lon: np.ndarray, coord_round: int = 4) -> np.ndarray:
    """Timezone chính xác (polygon của timezonefinder) cho từng toạ độ, sau khi làm tròn coord_round chữ số (~11 m)."""
    from timezonefinder import TimezoneFinder

    tf = TimezoneFinder()
    key = pd.DataFrame({"lat": np.round(lat, coord_round), "lon": np.round(lon, coord_round)})
    uniq = key.drop_duplicates().reset_index(drop=True)
    ok = uniq.lat.between(-90, 90) & uniq.lon.between(-180, 180)
    uniq["tz"] = "Unknown"
    uniq.loc[ok, "tz"] = [tf.timezone_at(lat=a, lng=o) or "Unknown" for a, o in zip(uniq.lat[ok], uniq.lon[ok])]
    return key.merge(uniq, on=["lat", "lon"], how="left")["tz"].to_numpy()


def add_geo(df: pd.DataFrame, coord_round: int = 4) -> pd.DataFrame:
    """Thêm tz, utc_offset_h (có DST), ts_local, in_china, city, in_beijing theo toạ độ.

    Timezone tra chính xác cho từng toạ độ duy nhất (xem NB02 mục 2). Toạ độ ngoài phạm vi nhận tz = "Unknown".
    """
    df["tz"] = pd.Categorical(lookup_tz(df.lat.to_numpy(), df.lon.to_numpy(), coord_round))
    offset_h = np.full(len(df), np.nan, dtype="float32")
    for tz, idx in df.groupby("tz", observed=True).indices.items():
        if tz == "Unknown":
            continue
        utc = df.ts_utc.iloc[idx].dt.tz_localize("UTC")
        local = utc.dt.tz_convert(tz).dt.tz_localize(None)
        offset_h[idx] = ((local - utc.dt.tz_localize(None)).dt.total_seconds() / 3600).to_numpy()
    df["utc_offset_h"] = np.where(np.isnan(offset_h), 8, offset_h).astype("float32")
    df["ts_local"] = df.ts_utc + pd.to_timedelta(df.utc_offset_h, unit="h")
    df["in_china"] = df.tz.isin(CHINA_TZ).to_numpy()
    df["city"] = pd.Categorical(nearest_city_fast(df.lat.to_numpy(), df.lon.to_numpy()))
    df["in_beijing"] = in_beijing(df.lat.to_numpy(), df.lon.to_numpy())
    return df


def nearest_city_fast(lat: np.ndarray, lon: np.ndarray, grid_deg: float = 0.05) -> np.ndarray:
    """Thành phố tham chiếu gần nhất, tính trên lưới grid_deg (chỉ dùng để mô tả khu vực, không dùng cho giờ local)."""
    g = pd.DataFrame({"a": np.round(lat / grid_deg).astype("int32"), "o": np.round(lon / grid_deg).astype("int32")})
    u = g.drop_duplicates().reset_index(drop=True)
    u["city"] = nearest_city(u.a.to_numpy() * grid_deg, u.o.to_numpy() * grid_deg)
    return g.merge(u, on=["a", "o"], how="left")["city"].to_numpy()


def china_calendar(years=range(2007, 2013)) -> pd.DataFrame:
    """Lịch chính thức của Trung Quốc: ngày nghỉ lễ và ngày cuối tuần làm bù (thư viện holidays)."""
    import re
    from datetime import date

    import holidays

    years = list(years)
    hol = holidays.China(years=years)
    days = pd.date_range(f"{min(years)}-01-01", f"{max(years)}-12-31", freq="D")
    swapped = {date.fromisoformat(m) for name in hol.values() for m in re.findall(r"由 (\d{4}-\d{2}-\d{2}) 调休", name)}
    d = days.date
    cal = pd.DataFrame({"date": days, "holiday_name": [hol.get(x) for x in d]})
    cal["is_holiday"] = np.isin(d, list(hol))
    cal["is_swapped_workday"] = np.isin(d, list(swapped))
    cal["is_workday"] = ((days.day_of_week < 5) & ~cal.is_holiday) | cal.is_swapped_workday
    return cal


def add_calendar(df: pd.DataFrame, cal: pd.DataFrame | None = None) -> pd.DataFrame:
    """Thêm is_workday, is_holiday theo ngày local: lịch chính thức nếu điểm ở Trung Quốc, T2–T6 nếu ở nơi khác."""
    cal = china_calendar() if cal is None else cal
    local_date = df.ts_local.dt.normalize()
    plain = (local_date.dt.day_of_week < 5).to_numpy()
    c = cal.set_index("date")
    cn_work = c.is_workday.reindex(local_date).to_numpy()
    cn_work = np.where(pd.isna(cn_work), plain, cn_work).astype(bool)
    cn_hol = c.is_holiday.reindex(local_date).fillna(False).to_numpy().astype(bool)
    in_cn = df.in_china.to_numpy()
    df["is_workday"] = np.where(in_cn, cn_work, plain)
    df["is_holiday"] = in_cn & cn_hol
    return df
