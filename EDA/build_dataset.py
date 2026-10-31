"""Parse toàn bộ Geolife (.plt + labels.txt) thành parquet để các notebook EDA đọc nhanh.

Output (data/processed/):
- points.parquet : mỗi dòng 1 điểm GPS (user, traj_id, lat, lon, alt_ft, ts_utc, mode)
- labels.parquet : các khoảng nhãn phương tiện (user, start_utc, end_utc, mode)
- files.parquet  : metadata từng file .plt (số dòng header, số điểm, tên file)

Chạy: uv run python EDA/build_dataset.py
"""
from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "Geolife_Trajectories" / "Data"
OUT = ROOT / "data" / "processed"

COLS = ["lat", "lon", "zero", "alt_ft", "days", "date", "time"]


def parse_user(user_dir: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    user_dir = Path(user_dir)
    user = int(user_dir.name)
    frames, meta = [], []
    for plt in sorted((user_dir / "Trajectory").glob("*.plt")):
        df = pd.read_csv(plt, skiprows=6, header=None, names=COLS)
        meta.append({"user": user, "traj_id": plt.stem, "n_points": len(df),
                     "file_bytes": plt.stat().st_size})
        if df.empty:
            continue
        df["ts_utc"] = pd.to_datetime(df["date"] + " " + df["time"], format="%Y-%m-%d %H:%M:%S")
        df["traj_id"] = plt.stem
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
        lab_sorted = lab.sort_values("start_utc")
        m = pd.merge_asof(pts[["ts_utc"]].reset_index(), lab_sorted[["start_utc", "end_utc", "mode"]],
                          left_on="ts_utc", right_on="start_utc", direction="backward")
        ok = m["ts_utc"] <= m["end_utc"]
        pts["mode"] = pd.Series(np.where(ok, m["mode"], None), index=m["index"]).reindex(pts.index)
        pts = pts.sort_index()
    else:
        lab = pd.DataFrame(columns=["user", "start_utc", "end_utc", "mode"])
        pts["mode"] = None
    return pts, lab, pd.DataFrame(meta)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    users = sorted(str(p) for p in RAW.iterdir() if p.is_dir())
    with ProcessPoolExecutor(max_workers=os.cpu_count()) as ex:
        results = list(ex.map(parse_user, users))
    pts = pd.concat([r[0] for r in results], ignore_index=True)
    labs = pd.concat([r[1] for r in results if len(r[1])], ignore_index=True)
    meta = pd.concat([r[2] for r in results], ignore_index=True)
    pts["mode"] = pts["mode"].astype("category")
    pts["traj_id"] = pts["traj_id"].astype("category")
    pts.to_parquet(OUT / "points.parquet", index=False)
    labs.to_parquet(OUT / "labels.parquet", index=False)
    meta.to_parquet(OUT / "files.parquet", index=False)
    print(f"points={len(pts):,} users={pts.user.nunique()} trajs={len(meta):,} labels={len(labs):,}")


if __name__ == "__main__":
    main()
