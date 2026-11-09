"""DBSCAN: GPS → visit (cụm DBSCAN trên ô lưới, trọng số thời gian) → home / office. Mỗi cụm là một place, nên không có bước
gom place riêng. Cách chọn toạ độ đại diện của ô lấy từ config (`cell_center`)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..clusters import detect_visits
from ..home_office import label_roles
from .base import Model


class DbscanModel(Model):
    name = "dbscan"

    def stays(self, points: pd.DataFrame) -> pd.DataFrame:
        """Bảng visit, cùng cột với bảng stay của stay_point, có sẵn cột place."""
        return detect_visits(points, self.params)

    def label(self, stays: pd.DataFrame, users) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """visits → (visits, bảng place, dự đoán). Dự đoán luôn có confidence (`confidence.add_confidence`)."""
        places, pred = label_roles(stays, users, self.params)
        return stays, places, pred

    def predict(self, points: pd.DataFrame):
        stays, _, pred = self.label(self.stays(points), np.unique(points.user))
        return stays, pred
