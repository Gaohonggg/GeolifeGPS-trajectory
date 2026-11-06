"""Chỉ số đánh giá bước stay. GeoLife không có nhãn home / office nên chỉ đo được chất lượng của stay.

| Chỉ số | Định nghĩa |
| --- | --- |
| `n_stays`, `stays_per_day` | Tỉ lệ tạo stay: số stay, và số stay / số (user, ngày local) có dữ liệu |
| `fake_share` | Tỉ lệ stay giả: trong các stay có >= 50% số điểm nằm trong khoảng có nhãn phương tiện, % stay có >= 50% số điểm mang nhãn di chuyển (`MOVING`) |
| `fragment_share` | % stay bắt đầu <= 15 phút sau stay trước và có tâm cách stay trước <= 250 m (một lần dừng bị chẻ đôi) |
| `long_stays` | Số stay >= 6 giờ (thời gian ở nhà / ở chỗ làm nằm trong các stay này) |

Diễn giải và giới hạn: docs/evaluation.md.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .geo import haversine
from .preprocess import label_points

# Nhãn coi là "đang di chuyển": phương tiện cơ giới + xe đạp. Không tính walk: đi bộ loanh quanh trong một nơi (khuôn viên,
# trung tâm thương mại) vẫn là đang ở nơi đó.
MOVING = ["bike", "bus", "car", "taxi", "subway", "train", "airplane", "motorcycle", "boat"]


def label_flags(points: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    """Hai cờ cho từng điểm (cùng thứ tự với points): có nhãn không, nhãn có thuộc MOVING không.
    Tính một lần rồi dùng lại cho nhiều bộ tham số."""
    mode = label_points(points[["user", "ts_utc"]], labels)
    return pd.DataFrame({"labeled": mode.notna().to_numpy(), "moving": mode.isin(MOVING).to_numpy()})


def stays_per_day(stays: pd.DataFrame, points: pd.DataFrame) -> float:
    days = pd.DataFrame({"user": points.user.to_numpy(), "day": points.ts_local.to_numpy().astype("datetime64[D]")})
    return len(stays) / len(days.drop_duplicates())


def fake_share(stays: pd.DataFrame, points: pd.DataFrame, flags: pd.DataFrame) -> float:
    # Vị trí của các điểm của stay trong bảng points: [điểm đầu của user + i0, điểm đầu của user + i1]
    first = pd.Series({u: ix[0] for u, ix in points.groupby("user", sort=True).indices.items()})
    a = first.reindex(stays.user).to_numpy() + stays.i0.to_numpy()
    b = first.reindex(stays.user).to_numpy() + stays.i1.to_numpy()
    n = b - a + 1
    # Số điểm có cờ trong đoạn [a, b] = hiệu của tổng cộng dồn
    labeled = np.r_[0, np.cumsum(flags.labeled)]
    moving = np.r_[0, np.cumsum(flags.moving)]
    in_labeled = (labeled[b + 1] - labeled[a]) / n >= 0.5
    is_fake = in_labeled & ((moving[b + 1] - moving[a]) / n >= 0.5)
    return is_fake.sum() / max(in_labeled.sum(), 1)


def fragment_share(stays: pd.DataFrame) -> float:
    s = stays.sort_values(["user", "start_utc"])
    prev = s.groupby("user").shift(1)
    gap_min = (s.start_utc - prev.end_utc) / 60
    dist_m = haversine(prev.lat, prev.lon, s.lat, s.lon)
    return float(((gap_min <= 15) & (dist_m <= 250)).mean())


def stay_metrics(stays: pd.DataFrame, points: pd.DataFrame, flags: pd.DataFrame) -> dict:
    return {
        "n_stays": len(stays),
        "stays_per_day": round(stays_per_day(stays, points), 3),
        "fake_share": round(float(fake_share(stays, points, flags)), 4),
        "fragment_share": round(fragment_share(stays), 4),
        "long_stays": int((stays.dur_h >= 6).sum()),
    }


def prediction_summary(pred: pd.DataFrame) -> dict:
    """Mô tả output home / office (không phải chỉ số đánh giá): bao nhiêu user có dự đoán, lý do abstain, phân bố confidence."""
    out = {}
    for role, g in pred.groupby("role"):
        out[role] = {"predicted": int(g.abstain_reason.isna().sum()), "users": len(g),
                     "abstain": g.abstain_reason.value_counts().to_dict()}
        if "confidence" in g:
            q = g.confidence.dropna().quantile([0.1, 0.25, 0.5, 0.75])
            out[role]["confidence"] = {f"p{int(k * 100)}": round(float(v), 3) for k, v in q.items()}
    return out
