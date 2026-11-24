"""Logic endpoint dự đoán, không phụ thuộc HTTP."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

import pandas as pd

from .errors import ApiError
from .model import LoadedModel


class PointStore(Protocol):
    """Nguồn điểm GPS theo user."""

    def ping(self) -> bool:
        """Nguồn có đọc được không."""

    def user_exists(self, user_id: int) -> bool: ...

    def fetch_points(self, user_id: int, start: datetime | None = None, end: datetime | None = None) -> pd.DataFrame:
        """Điểm trong [start, end), sort theo thời gian, ts_utc dạng naive UTC; cột theo geolife.models.base.POINT_COLS."""


def parse_time(name: str, value: str | None) -> datetime | None:
    """ISO 8601 bắt buộc có offset (`2008-10-23T02:53:04Z`); không nhận Unix timestamp."""
    if value is None:
        return None
    try:
        t = datetime.fromisoformat(value)
    except ValueError:
        raise ApiError(400, "invalid_request", f"{name} must be an ISO 8601 date-time, e.g. 2008-10-23T02:53:04Z") from None
    if t.tzinfo is None:
        raise ApiError(400, "invalid_request", f"{name} must include a UTC offset, e.g. 2008-10-23T02:53:04Z")
    try:
        # thời điểm sát năm 1 hoặc năm 9999 tràn khỏi khoảng của datetime khi đổi sang UTC
        return t.astimezone(UTC)
    except OverflowError:
        raise ApiError(400, "invalid_request", f"{name} is out of range") from None


def check_time_range(start: datetime | None, end: datetime | None) -> None:
    if start is not None and end is not None and start >= end:
        raise ApiError(400, "invalid_time_range", "start must be before end")


def _iso(ts: pd.Timestamp) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def predict_user(store: PointStore, model: LoadedModel, user_id: int,
                 start: str | None = None, end: str | None = None) -> dict:
    start, end = parse_time("start", start), parse_time("end", end)
    check_time_range(start, end)
    if not store.user_exists(user_id):
        raise ApiError(404, "user_not_found", f"user {user_id} not found")
    points = store.fetch_points(user_id, start, end)
    if points.empty:
        raise ApiError(404, "no_points", f"user {user_id} has no points between {_bound(start)} and {_bound(end)}")
    return {
        "user_id": user_id,
        "n_points": len(points),
        "time_range": {"start": _iso(points.ts_utc.iloc[0]), "end": _iso(points.ts_utc.iloc[-1])},
        "model": model.info.model_dump(),
        **model.predict(points),
    }


def _bound(t: datetime | None) -> str:
    return "-" if t is None else t.isoformat()
