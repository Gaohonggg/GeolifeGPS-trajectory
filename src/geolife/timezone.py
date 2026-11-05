"""Giờ local theo timezone thật của từng toạ độ (có DST), và quốc gia của timezone."""
from __future__ import annotations

import importlib.resources
from functools import lru_cache

import numpy as np
import pandas as pd
from timezonefinder import TimezoneFinder

UNKNOWN = "Unknown"


def lookup_tz(lat: np.ndarray, lon: np.ndarray, coord_round: int = 4) -> pd.Categorical:
    """Timezone IANA của từng điểm. Tra một lần cho mỗi toạ độ duy nhất sau khi làm tròn `coord_round` chữ số."""
    key = pd.DataFrame({"lat": np.round(lat, coord_round), "lon": np.round(lon, coord_round)})
    uniq = key.drop_duplicates().reset_index(drop=True)
    tf = TimezoneFinder()
    uniq["tz"] = [tf.timezone_at(lat=a, lng=o) or UNKNOWN for a, o in zip(uniq.lat, uniq.lon)]
    return pd.Categorical(key.merge(uniq, on=["lat", "lon"], how="left")["tz"])


def to_local(ts_utc: pd.Series, tz: pd.Categorical | pd.Series, fallback_tz: str = "Asia/Shanghai") -> pd.Series:
    """ts_local (naive) = ts_utc đổi sang timezone của từng điểm, offset tính tại đúng thời điểm đó (có DST)."""
    tz = pd.Series(tz, index=ts_utc.index)
    out = pd.Series(pd.NaT, index=ts_utc.index, dtype="datetime64[us]")
    for name, idx in tz.groupby(tz, observed=True).groups.items():
        zone = fallback_tz if name == UNKNOWN else name
        out.loc[idx] = ts_utc.loc[idx].dt.tz_localize("UTC").dt.tz_convert(zone).dt.tz_localize(None).astype("datetime64[us]")
    return out


@lru_cache
def _zone_country() -> dict[str, str]:
    text = importlib.resources.files("tzdata.zoneinfo").joinpath("zone.tab").read_text()
    rows = (line.split("\t") for line in text.splitlines() if line and not line.startswith("#"))
    return {r[2]: r[0] for r in rows}


def tz_country(tz_names) -> np.ndarray:
    """Mã quốc gia ISO của timezone (theo zone.tab của tzdata); "" khi timezone không thuộc quốc gia nào."""
    m = _zone_country()
    return np.array([m.get(t, "") for t in tz_names], dtype=object)
