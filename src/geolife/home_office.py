"""Gán home / office cho từng user từ các place.

Một lượt duy nhất cho cả hai vai trò:
1. Cắt mỗi stay thành các lát theo từng giờ local (một stay 23:30–08:10 thành 10 lát). Việc cắt chỉ làm một lần.
2. Mỗi lát được gắn hai cờ, tính vector hoá trên cùng một bảng:
   - `home`: lát nằm trong khung đêm. Áp cho **mọi ngày**, gồm cả ngày nghỉ lễ và cuối tuần: đêm nào user cũng về nhà.
   - `office`: lát nằm trong khung hành chính **của ngày làm việc**. Ngày làm việc lấy từ lịch của đúng quốc gia của stay:
     T2–T6 trừ ngày nghỉ lễ, cộng ngày làm bù (`calendar.WorkCalendar`).
3. Gom theo (user, place) một lần, ra cùng lúc giờ / số đêm cho home và giờ / số ngày làm việc cho office.
Không lọc dữ liệu rồi chạy lại cho từng vai trò: hai vai trò chỉ khác nhau ở cột trọng số.

Home: place có nhiều giờ đêm nhất, với ít nhất `min_nights` đêm khác nhau.
Office: place có nhiều giờ hành chính nhất, cách home > `same_place_m`, với ít nhất `min_workdays` ngày làm việc khác nhau.
Không thoả điều kiện thì trả về null kèm lý do, không đoán bừa.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .calendar import WorkCalendar
from .confidence import CONF_COLS, add_confidence
from .geo import haversine
from .timezone import tz_country

HOUR = 3600
PLACE_COLS = ["user", "place", "lat", "lon", "n_stays", "total_h", "home_h", "nights", "office_h", "workdays"]
PRED_COLS = ["user", "role", "place", "lat", "lon", "hours", "days", "abstain_reason"]


def hour_slices(start_local: np.ndarray, end_local: np.ndarray):
    """Mỗi khoảng [start, end) (giây local) thành các lát theo giờ. Trả về (chỉ số khoảng, số giờ của lát, giờ bắt đầu lát)."""
    start, end = np.asarray(start_local, np.float64), np.asarray(end_local, np.float64)
    h0 = np.floor(start / HOUR)
    n = np.maximum(np.ceil(end / HOUR) - h0, 1).astype(np.int64)
    vid = np.repeat(np.arange(len(start)), n)
    hb = h0[vid] + (np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n))
    h = (np.minimum((hb + 1) * HOUR, end[vid]) - np.maximum(hb * HOUR, start[vid])) / HOUR
    keep = h > 0
    return vid[keep], h[keep], hb[keep]


def in_window(hour: np.ndarray, window) -> np.ndarray:
    a, b = window
    return (hour >= a) & (hour < b) if a < b else (hour >= a) | (hour < b)


def role_slices(stays: pd.DataFrame, cal: WorkCalendar, night, work) -> pd.DataFrame:
    """Bảng lát giờ của mọi stay, kèm cờ home / office và ngày dùng để đếm (đêm gán cho ngày bắt đầu đêm)."""
    vid, h, hb = hour_slices(stays.start_local.to_numpy(), stays.end_local.to_numpy())
    hour = (hb % 24).astype(np.int64)
    day = np.floor(hb / 24).astype(np.int64)
    country = tz_country(stays.tz.to_numpy())[vid]
    home = in_window(hour, night)
    office = in_window(hour, work) & cal.is_workday(country, day)
    night_day = np.floor((hb - night[1]) / 24).astype(np.int64)
    return pd.DataFrame({"user": stays.user.to_numpy()[vid], "place": stays.place.to_numpy()[vid], "h": h,
                         "home": home, "office": office, "night_day": night_day, "day": day})


def place_table(stays: pd.DataFrame, sl: pd.DataFrame) -> pd.DataFrame:
    """Một dòng mỗi (user, place): toạ độ (tâm theo thời lượng stay), tổng giờ, giờ / số đêm, giờ / số ngày làm việc."""
    w = stays.dur_h.clip(lower=1e-9)
    xy = (stays.assign(wl=stays.lat * w, wo=stays.lon * w, w=w).groupby(["user", "place"])[["wl", "wo", "w"]].sum())
    p = pd.DataFrame({"lat": xy.wl / xy.w, "lon": xy.wo / xy.w, "n_stays": stays.groupby(["user", "place"]).size()})
    sl = sl.assign(home_h=sl.h * sl.home, office_h=sl.h * sl.office,
                   home_day=sl.night_day.where(sl.home), office_day=sl.day.where(sl.office))
    agg = sl.groupby(["user", "place"]).agg(total_h=("h", "sum"), home_h=("home_h", "sum"), nights=("home_day", "nunique"),
                                            office_h=("office_h", "sum"), workdays=("office_day", "nunique"))
    return p.join(agg).fillna(0).reset_index()


def pick_roles(places: pd.DataFrame, users, min_nights: int, min_workdays: int, same_place_m: float) -> pd.DataFrame:
    """Một dòng mỗi (user, role). abstain_reason = None khi có dự đoán."""
    rows = []
    P = dict(tuple(places.groupby("user")))
    for u in users:
        p = P.get(u, places.iloc[:0])
        cand = p[p.home_h > 0]
        home = None
        if len(cand) == 0:
            rows.append(_row(u, "home", None, "no_night_stay"))
        elif (ok := cand[cand.nights >= min_nights]).empty:
            rows.append(_row(u, "home", None, "insufficient_nights"))
        else:
            home = ok.loc[ok.home_h.idxmax()]
            rows.append(_row(u, "home", home))
        cand = p[p.office_h > 0]
        if home is not None:
            cand = cand[haversine(home.lat, home.lon, cand.lat, cand.lon) > same_place_m]
        if len(cand) == 0:
            rows.append(_row(u, "office", None, "no_distinct_office"))
        elif (ok := cand[cand.workdays >= min_workdays]).empty:
            rows.append(_row(u, "office", None, "insufficient_workdays"))
        else:
            rows.append(_row(u, "office", ok.loc[ok.office_h.idxmax()]))
    return pd.DataFrame(rows, columns=PRED_COLS)


def label_roles(stays: pd.DataFrame, users, p: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Stay đã có cột place → (bảng place, dự đoán home / office kèm confidence). Dùng chung cho mọi model.
    p: params của model (khung giờ, min_nights, min_workdays, same_place_m, khối confidence).
    Không có stay nào (input quá ít hoặc user chỉ di chuyển): mọi user abstain (`no_night_stay`, `no_distinct_office`),
    confidence để trống."""
    if stays.empty:
        places = pd.DataFrame(columns=PLACE_COLS)
        pred = pick_roles(places, users, p["min_nights"], p["min_workdays"], p["same_place_m"])
        return places, pred.assign(**{c: np.nan for c in CONF_COLS})
    years = range(int(pd.Timestamp(stays.start_local.min(), unit="s").year) - 1,
                  int(pd.Timestamp(stays.end_local.max(), unit="s").year) + 2)
    cal = WorkCalendar(np.unique(tz_country(stays.tz.unique())), years)
    sl = role_slices(stays, cal, tuple(p["night_hours"]), tuple(p["work_hours"]))
    places = place_table(stays, sl)
    pred = pick_roles(places, users, p["min_nights"], p["min_workdays"], p["same_place_m"])
    return places, add_confidence(pred, places, sl, p)


def _row(u, role, r, reason=None):
    if r is None:
        return {"user": u, "role": role, "place": -1, "lat": np.nan, "lon": np.nan, "hours": 0.0, "days": 0,
                "abstain_reason": reason}
    hours, days = (r.home_h, r.nights) if role == "home" else (r.office_h, r.workdays)
    return {"user": u, "role": role, "place": int(r.place), "lat": r.lat, "lon": r.lon, "hours": float(hours),
            "days": int(days), "abstain_reason": None}
