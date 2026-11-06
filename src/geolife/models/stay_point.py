"""Stay-point: GPS → stay (Li et al., 2008) → place → home / office."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..calendar import WorkCalendar
from ..home_office import pick_roles, place_table, role_slices
from ..places import assign_places
from ..stays import detect_stays
from ..timezone import tz_country
from .base import Model


class StayPointModel(Model):
    name = "stay_point"

    def stays(self, points: pd.DataFrame) -> pd.DataFrame:
        p = self.params
        return detect_stays(points, p["D_m"], p["T_min"], p["max_gap_h"])

    def label(self, stays: pd.DataFrame, users) -> tuple[pd.DataFrame, pd.DataFrame]:
        """stays → (stays có cột place, bảng place, dự đoán)."""
        p = self.params
        stays = stays.assign(place=assign_places(stays, p["place_eps_m"]).to_numpy())
        years = range(int(pd.Timestamp(stays.start_local.min(), unit="s").year) - 1,
                      int(pd.Timestamp(stays.end_local.max(), unit="s").year) + 2)
        cal = WorkCalendar(np.unique(tz_country(stays.tz.unique())), years)
        sl = role_slices(stays, cal, tuple(p["night_hours"]), tuple(p["work_hours"]))
        places = place_table(stays, sl)
        pred = pick_roles(places, users, p["min_nights"], p["min_workdays"], p["same_place_m"])
        return stays, places, pred

    def predict(self, points: pd.DataFrame):
        stays, _, pred = self.label(self.stays(points), np.unique(points.user))
        return stays, pred
