"""Stay-point: GPS → stay → place → home / office. Cách đặt neo của stay lấy từ config (`anchor`, mặc định "first")."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..home_office import label_roles
from ..places import assign_places
from ..stays import detect_stays
from .base import Model


class StayPointModel(Model):
    name = "stay_point"

    def stays(self, points: pd.DataFrame) -> pd.DataFrame:
        p = self.params
        return detect_stays(points, p["D_m"], p["T_min"], p["max_gap_h"], p.get("anchor", "first"))

    def label(self, stays: pd.DataFrame, users) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """stays → (stays có cột place, bảng place, dự đoán). Dự đoán luôn có confidence (`confidence.add_confidence`)."""
        stays = stays.assign(place=assign_places(stays, self.params["place_eps_m"]).to_numpy())
        places, pred = label_roles(stays, users, self.params)
        return stays, places, pred

    def predict(self, points: pd.DataFrame):
        stays, _, pred = self.label(self.stays(points), np.unique(points.user))
        return stays, pred
