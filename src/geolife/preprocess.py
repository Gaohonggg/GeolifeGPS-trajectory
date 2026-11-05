"""Các bước làm sạch điểm GPS. Notebook `preprocess/v_*/preprocess.ipynb` gọi lần lượt và in mẫu kiểm tra.

Quy ước chung: bảng điểm luôn sort theo (user, ts_utc) và có cột `traj_key` = "<user>_<traj_id>". Tốc độ giữa hai điểm
chỉ tính khi chúng cùng file (`traj_key`): hai file liền nhau có thể cách nhau nhiều giờ.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import polars as pl
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from .geo import haversine

# ---------------------------------------------------------------- tiện ích


def add_kinematics(df: pd.DataFrame) -> pd.DataFrame:
    """dt_s, dist_m, speed_kmh so với điểm trước trong cùng file (NaN ở điểm đầu file)."""
    k = df["traj_key"].to_numpy()
    same = k[1:] == k[:-1]
    lat, lon = df["lat"].to_numpy(), df["lon"].to_numpy()
    ts = df["ts_utc"].to_numpy().astype("datetime64[s]").astype(np.int64).astype(np.float64)
    dt = np.full(len(df), np.nan)
    dist = np.full(len(df), np.nan)
    dt[1:] = np.where(same, ts[1:] - ts[:-1], np.nan)
    dist[1:] = np.where(same, haversine(lat[:-1], lon[:-1], lat[1:], lon[1:]), np.nan)
    df["dt_s"], df["dist_m"] = dt, dist
    with np.errstate(divide="ignore", invalid="ignore"):
        df["speed_kmh"] = np.where(dt > 0, dist / dt * 3.6, np.nan)
    return df


def drop_trajs(df: pd.DataFrame, keys) -> pd.DataFrame:
    return add_kinematics(df[~df.traj_key.isin(set(keys))].reset_index(drop=True))


def drop_points(df: pd.DataFrame, mask: np.ndarray) -> pd.DataFrame:
    return add_kinematics(df[~mask].reset_index(drop=True))


def label_points(df: pd.DataFrame, labels: pd.DataFrame) -> pd.Series:
    """Nhãn phương tiện của từng điểm (None nếu không nằm trong khoảng có nhãn). Chỉ dùng để kiểm tra chéo."""
    out = pd.Series(None, index=df.index, dtype=object)
    order = df.ts_utc.to_numpy().argsort(kind="stable")
    left = df[["user", "ts_utc"]].iloc[order].reset_index()
    m = pd.merge_asof(left.sort_values("ts_utc"), labels.sort_values("start_utc"), left_on="ts_utc",
                      right_on="start_utc", by="user", direction="backward")
    hit = (m.ts_utc <= m.end_utc).to_numpy()
    out.loc[m["index"].to_numpy()[hit]] = m["mode"].to_numpy()[hit]
    return out


# ---------------------------------------------------------------- bước 2: giá trị không hợp lệ, trùng timestamp


def invalid_mask(df: pd.DataFrame, lat_range, lon_range, years) -> np.ndarray:
    y = df.ts_utc.dt.year
    ok = df.lat.between(*lat_range) & df.lon.between(*lon_range) & y.between(*years)
    return ~ok.to_numpy()


def duplicate_timestamp_mask(df: pd.DataFrame) -> np.ndarray:
    """Điểm trùng (user, ts_utc) với một điểm đứng trước; df đã sort ổn định theo (user, ts_utc)."""
    return df.duplicated(["user", "ts_utc"], keep="first").to_numpy()


# ---------------------------------------------------------------- bước 3 và 9: user trùng dữ liệu


def components(users, pairs: pd.DataFrame) -> pd.Series:
    """Thành phần liên thông của đồ thị user (cạnh = các cặp user_a, user_b). Trả về group id theo user."""
    users = np.sort(np.unique(users))
    ix = {u: i for i, u in enumerate(users)}
    a = [ix[u] for u in pairs.user_a]
    b = [ix[u] for u in pairs.user_b]
    m = coo_matrix((np.ones(len(a)), (a, b)), shape=(len(users), len(users)))
    _, lab = connected_components(m, directed=False)
    return pd.Series(lab, index=pd.Index(users, name="user"), name="group")


def duplicate_file_pairs(files: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """File giống hệt nhau ở nhiều user: cùng tên, cùng số điểm, cùng điểm đầu, cùng thời điểm cuối.

    Trả về (files có thêm dup_id, is_cross_dup; bảng cặp user_a < user_b kèm số file chung).
    """
    files = files.copy()
    files["dup_id"] = files.groupby(["traj_id", "n_raw", "lat0", "lon0", "t_end"]).ngroup()
    files["is_cross_dup"] = files.duplicated("dup_id", keep=False)
    d = files.loc[files.is_cross_dup, ["dup_id", "user"]]
    p = d.merge(d, on="dup_id").query("user_x < user_y")
    pairs = p.groupby(["user_x", "user_y"]).size().rename("shared_files").reset_index()
    return files, pairs.rename(columns={"user_x": "user_a", "user_y": "user_b"})


def colocation_pairs(df: pd.DataFrame, minute: int = 1, cell_deg: float = 0.001) -> pd.DataFrame:
    """Cặp user cùng có mặt trong một ô ~100 m ở cùng một phút.

    share = số (phút, ô) chung / số (phút, ô) của user ít dữ liệu hơn. Dùng để bắt các user "gần trùng" mà khoá file
    không bắt được (ví dụ hai thiết bị đi cùng nhau, hoặc file bị cắt khác nhau).
    """
    k = pl.DataFrame({
        "user": df.user.to_numpy(),
        "t": df.ts_utc.to_numpy().astype("datetime64[s]").astype(np.int64) // (60 * minute),
        "a": np.floor(df.lat.to_numpy() / cell_deg).astype(np.int64),
        "o": np.floor(df.lon.to_numpy() / cell_deg).astype(np.int64),
    }).unique()
    n = k.group_by("user").len().rename({"len": "n"})
    p = (k.join(k, on=["t", "a", "o"]).filter(pl.col("user") < pl.col("user_right"))
         .group_by(["user", "user_right"]).len().rename({"user": "user_a", "user_right": "user_b", "len": "shared"}))
    p = (p.join(n.rename({"user": "user_a", "n": "n_a"}), on="user_a")
          .join(n.rename({"user": "user_b", "n": "n_b"}), on="user_b")
          .with_columns((pl.col("shared") / pl.min_horizontal("n_a", "n_b")).alias("share")))
    return p.sort("share", descending=True).to_pandas()


# ---------------------------------------------------------------- bước 4–6: file bay, file hỏng, spike


def traj_median_speed(df: pd.DataFrame) -> pd.Series:
    return df.groupby("traj_key", sort=False, observed=True).speed_kmh.median()


def find_spikes(df: pd.DataFrame, speed_kmh: float, return_ratio: float) -> np.ndarray:
    """Điểm B kiểu A → B → C trong cùng file: tốc độ vào và ra đều > speed_kmh, và C quay về gần A
    (d(A, C) < return_ratio · d(A, B))."""
    k = df["traj_key"].to_numpy()
    has_prev = np.r_[False, k[1:] == k[:-1]]
    has_next = np.r_[k[1:] == k[:-1], False]
    v_in = df["speed_kmh"].to_numpy()
    v_out = np.r_[v_in[1:], np.nan]
    lat, lon = df["lat"].to_numpy(), df["lon"].to_numpy()
    d_ac = np.r_[np.nan, haversine(lat[:-2], lon[:-2], lat[2:], lon[2:]), np.nan]
    return has_prev & has_next & (v_in > speed_kmh) & (v_out > speed_kmh) & (d_ac < return_ratio * df["dist_m"].to_numpy())


def remove_spikes(df: pd.DataFrame, speed_kmh: float, return_ratio: float, max_iter: int = 3):
    """Xoá spike, lặp lại vì xoá một spike có thể làm lộ spike kế bên. Trả về (df, số điểm xoá mỗi vòng)."""
    removed = []
    for _ in range(max_iter):
        s = find_spikes(df, speed_kmh, return_ratio)
        removed.append(int(s.sum()))
        if not s.any():
            break
        df = drop_points(df, s)
    return df, removed


# ---------------------------------------------------------------- bước 7: điểm không có liên kết hợp lý


def segments(df: pd.DataFrame, speed_kmh: float, gap_s: float) -> tuple[pd.DataFrame, np.ndarray]:
    """Cắt mỗi file thành các đoạn tại: liên kết có tốc độ > speed_kmh (bước nhảy) và khoảng không ghi > gap_s.
    Bên trong một đoạn, các điểm nối nhau bằng liên kết hợp lý (nhanh vừa phải, sát nhau về thời gian), tức là tự nhất quán.

    Trả về (bảng theo đoạn, mã đoạn của từng điểm). Bảng gồm first, last (chỉ số điểm), n_points, dur_s, fast_before,
    fast_after (đầu / cuối đoạn có phải bước nhảy không; mép file và khoảng không ghi không tính là bước nhảy).
    """
    k = df["traj_key"].to_numpy()
    fast_in = df["speed_kmh"].to_numpy() > speed_kmh            # liên kết từ điểm trước tới điểm này
    gap_in = df["dt_s"].to_numpy() > gap_s
    new_file = np.r_[True, k[1:] != k[:-1]]
    start = new_file | fast_in | gap_in
    seg = np.cumsum(start) - 1
    first = np.flatnonzero(start)
    last = np.r_[first[1:], len(df)] - 1
    ts = df["ts_utc"].to_numpy().astype("datetime64[s]").astype(np.int64)
    fast_after = np.r_[fast_in[first[1:]], False]
    return pd.DataFrame({"first": first, "last": last, "n_points": last - first + 1, "dur_s": ts[last] - ts[first],
                         "fast_before": fast_in[first], "fast_after": fast_after}), seg


def island_mask(df: pd.DataFrame, speed_kmh: float, gap_s: float, max_points: int) -> tuple[np.ndarray, pd.DataFrame]:
    """Điểm thuộc "đảo": đoạn có <= max_points điểm và có ít nhất một đầu là bước nhảy > speed_kmh
    (đầu còn lại là bước nhảy, mép file, hoặc khoảng không ghi).

    Nói cách khác: điểm không có liên kết hợp lý nào với hàng xóm, mà lại có ít nhất một liên kết bất khả thi.
    - Điểm lạc đơn lẻ (vào nhanh, ra nhanh); đoạn bay trong file hỗn hợp (chuỗi điểm lạc liên tiếp).
    - Fix sai ngay khi bật máy hoặc ngay sau khi mất tín hiệu (mép file / khoảng không ghi → bước nhảy).
    - Bước nhảy giữa hai đoạn dài (mất tín hiệu rồi bắt lại): cả hai đoạn tự nhất quán nên được giữ.
    """
    seg_tab, seg = segments(df, speed_kmh, gap_s)
    is_island = (seg_tab.n_points <= max_points) & (seg_tab.fast_before | seg_tab.fast_after)
    return is_island.to_numpy()[seg], seg_tab.assign(island=is_island)


# ---------------------------------------------------------------- bước 10: chia dev / holdout


def user_table(df: pd.DataFrame, files: pd.DataFrame, labels: pd.DataFrame, group: pd.Series) -> pd.DataFrame:
    """Một dòng mỗi user: lượng dữ liệu, có nhãn phương tiện không, tỉ lệ dữ liệu là bản sao, nhóm."""
    g = df.groupby("user")
    u = pd.DataFrame({
        "n_points": g.size(),
        "n_trajs": g.traj_key.nunique(),
        "days": df.ts_local.dt.normalize().groupby(df.user).nunique(),
    })
    u["point_share"] = u.n_points / u.n_points.sum()
    u["has_labels"] = u.index.isin(labels.user.unique())
    dup = files[files.is_cross_dup].groupby("user").n_raw.sum()
    u["dup_share"] = (dup / files.groupby("user").n_raw.sum()).reindex(u.index).fillna(0.0)
    u["group"] = group.reindex(u.index).astype(int)
    u["group_size"] = u.group.map(u.group.value_counts())
    return u


def split_groups(u: pd.DataFrame, holdout_frac: float, max_holdout_group_share: float, n_strata: int, seed: int) -> pd.Series:
    """Gán cả nhóm vào dev hoặc holdout.

    - Nhóm chiếm > max_holdout_group_share số điểm bị ép vào dev, để kết quả holdout không bị một nhóm lấn át.
    - Các nhóm còn lại được phân tầng theo (có nhãn phương tiện hay không) × (số ngày có dữ liệu, n_strata phân vị),
      rồi trong mỗi tầng lần lượt đưa nhóm ngẫu nhiên vào holdout tới khi đạt holdout_frac số user. Tầng "có nhãn" giữ
      cho cả hai phía đều tính được tỉ lệ stay giả.
    """
    rng = np.random.default_rng(seed)
    grp = u.groupby("group").agg(size=("n_points", "size"), share=("point_share", "sum"), days=("days", "sum"),
                                 has_labels=("has_labels", "any"))
    side = {g: "dev" for g in grp.index[grp.share > max_holdout_group_share]}
    rest = grp.drop(index=list(side))
    stratum = rest.has_labels.astype(int) * n_strata + pd.qcut(rest.days.rank(method="first"), n_strata, labels=False)
    for _, gs in rest.groupby(stratum):
        target, acc = holdout_frac * gs["size"].sum(), 0
        for gid in rng.permutation(gs.index.to_numpy()):
            if acc + gs.at[gid, "size"] <= target + 0.5:
                side[gid], acc = "holdout", acc + gs.at[gid, "size"]
            else:
                side[gid] = "dev"
    return u.group.map(side).rename("split")
