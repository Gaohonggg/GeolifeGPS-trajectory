"""Đọc dữ liệu thô GeoLife và output của preprocess."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
from joblib import Parallel, delayed

from .paths import RAW, preprocess_dir

PLT_COLS = ["lat", "lon", "zero", "alt_ft", "days", "date", "time"]
LABEL_COLS = ["user", "start_utc", "end_utc", "mode"]


def read_user(user_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Mọi file .plt và labels.txt của một user.

    Trả về (điểm, nhãn, metadata từng file). Điểm có các cột user, traj_id, ts_utc, lat, lon; altitude bị bỏ.
    Metadata gồm khoá nhận diện file trùng giữa các user: tên file, số điểm, điểm đầu, thời điểm cuối.
    """
    user = int(user_dir.name)
    frames, meta = [], []
    for f in sorted((user_dir / "Trajectory").glob("*.plt")):
        df = pd.read_csv(f, skiprows=6, header=None, names=PLT_COLS, usecols=["lat", "lon", "date", "time"])
        if df.empty:
            continue
        df["ts_utc"] = pd.to_datetime(df["date"] + " " + df["time"], format="%Y-%m-%d %H:%M:%S")
        df["traj_id"] = f.stem
        meta.append({"user": user, "traj_id": f.stem, "n_raw": len(df), "lat0": df.lat.iat[0],
                     "lon0": df.lon.iat[0], "t_end": df.ts_utc.iat[-1]})
        frames.append(df[["traj_id", "ts_utc", "lat", "lon"]])
    pts = pd.concat(frames, ignore_index=True)
    pts.insert(0, "user", np.int16(user))
    lab = pd.DataFrame(columns=LABEL_COLS)
    if (user_dir / "labels.txt").exists():
        lab = pd.read_csv(user_dir / "labels.txt", sep="\t")
        lab.columns = ["start_utc", "end_utc", "mode"]
        for c in ["start_utc", "end_utc"]:
            lab[c] = pd.to_datetime(lab[c], format="%Y/%m/%d %H:%M:%S")
        lab.insert(0, "user", np.int16(user))
    return pts, lab, pd.DataFrame(meta)


def read_raw(raw_dir: Path = RAW, n_jobs: int = -1) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Đọc toàn bộ dataset song song theo user. Trả về (điểm, nhãn, metadata file)."""
    dirs = sorted(p for p in Path(raw_dir).iterdir() if p.is_dir())
    res = Parallel(n_jobs=n_jobs)(delayed(read_user)(d) for d in dirs)
    pts = pd.concat([r[0] for r in res], ignore_index=True)
    labels = pd.concat([r[1] for r in res if len(r[1])], ignore_index=True)
    files = pd.concat([r[2] for r in res], ignore_index=True)
    labels["user"] = labels.user.astype(np.int16)
    return pts, labels, files


# ---------------------------------------------------------------- output của preprocess

def load_points(version: int, users=None, columns: list[str] | None = None) -> pd.DataFrame:
    """points.parquet của preprocess v_<version>, sort theo (user, ts_utc)."""
    q = pl.scan_parquet(preprocess_dir(version) / "points.parquet")
    if columns is not None:
        q = q.select(columns)
    if users is not None:
        q = q.filter(pl.col("user").is_in([int(u) for u in users]))
    return q.collect().to_pandas()


def load_labels(version: int) -> pd.DataFrame:
    return pd.read_parquet(preprocess_dir(version) / "labels.parquet")


def load_users(version: int) -> pd.DataFrame:
    return pd.read_parquet(preprocess_dir(version) / "users.parquet")


def split_users(version: int, split: str) -> list[int]:
    """User của một split ("dev" / "holdout" / "all")."""
    u = load_users(version)
    return sorted(u.index if split == "all" else u.index[u.split == split])
