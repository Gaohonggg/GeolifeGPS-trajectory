"""Lịch ngày làm việc theo quốc gia.

Ngày làm việc = (T2–T6 và không phải ngày nghỉ lễ) hoặc là ngày làm bù.
- Ngày nghỉ lễ lấy từ thư viện `holidays` theo đúng quốc gia của toạ độ.
- Ngày làm bù (thứ Bảy / Chủ nhật phải đi làm) chỉ có ở Trung Quốc trong dữ liệu này; `holidays.China` ghi nó trong tên
  ngày nghỉ được hoán đổi, dạng "休息日（由 2008-09-27 调休）" (ngày 27/9 thành ngày làm việc).
- Toạ độ không thuộc quốc gia nào (vd. `Etc/GMT-10` trên biển) hoặc quốc gia không có trong `holidays`: dùng T2–T6.

Ngày được biểu diễn bằng số ngày kể từ 1970-01-01 (int), để tra cứu vector hoá.
"""
from __future__ import annotations

import re
from datetime import date

import holidays
import numpy as np
import pandas as pd

_SWAP = re.compile(r"由 (\d{4}-\d{2}-\d{2}) 调休")
_EPOCH = date(1970, 1, 1)


def _day(d: date) -> int:
    return (d - _EPOCH).days


def weekday_rule(day: np.ndarray) -> np.ndarray:
    """T2–T6. 1970-01-01 là thứ Năm."""
    return (np.asarray(day) + 3) % 7 < 5


class WorkCalendar:
    def __init__(self, countries, years):
        years = list(years)
        self.years = years
        self.holidays: dict[str, dict[int, str]] = {}
        self.swapped: dict[str, set[int]] = {}
        supported = holidays.list_supported_countries()
        for c in sorted(set(countries)):
            if c not in supported:
                continue
            h = holidays.country_holidays(c, years=years)
            self.holidays[c] = {_day(d): name for d, name in h.items()}
            self.swapped[c] = {_day(date.fromisoformat(m)) for name in h.values() for m in _SWAP.findall(name)}

    def is_workday(self, country: np.ndarray, day: np.ndarray) -> np.ndarray:
        """country: mã ISO từng dòng; day: số ngày kể từ epoch theo giờ local."""
        country, day = np.asarray(country), np.asarray(day, dtype=np.int64)
        out = weekday_rule(day)
        for c in np.unique(country):
            if c not in self.holidays:
                continue
            m = country == c
            hol = np.isin(day[m], np.fromiter(self.holidays[c], dtype=np.int64))
            swp = np.isin(day[m], np.fromiter(self.swapped[c], dtype=np.int64, count=len(self.swapped[c])))
            out[m] = (out[m] & ~hol) | swp
        return out

    def table(self, country: str) -> pd.DataFrame:
        """Lịch theo ngày của một quốc gia, để kiểm tra bằng mắt."""
        days = pd.date_range(f"{min(self.years)}-01-01", f"{max(self.years)}-12-31", freq="D")
        d = (days.values.astype("datetime64[D]").astype(np.int64))
        hol = self.holidays.get(country, {})
        return pd.DataFrame({"date": days, "weekday": days.day_name().str[:3],
                             "holiday": [hol.get(x) for x in d],
                             "swapped_workday": np.isin(d, list(self.swapped.get(country, set()))),
                             "is_workday": self.is_workday(np.full(len(d), country), d)})
