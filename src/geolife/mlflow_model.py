"""Bọc một model version thành MLflow pyfunc để đăng ký vào registry và nạp lại ở API.

Một version trong registry tự chứa đủ để chạy: code thuật toán (thư mục `src/geolife`, đi kèm qua `code_paths`) và
`config.yaml` của version đó (artifact `config`). Nơi nạp model không cần cài package `geolife`.

    model = mlflow.pyfunc.load_model("models:/geolife_home_office/2")
    pred = model.predict(points)   # points: các cột POINT_COLS, sort theo (user, ts_utc)
"""
from __future__ import annotations

from pathlib import Path

import mlflow.pyfunc
import pandas as pd
import yaml

from .models import REGISTRY
from .models.base import POINT_COLS


class HomeOfficeModel(mlflow.pyfunc.PythonModel):
    def load_context(self, context):
        cfg = yaml.safe_load(Path(context.artifacts["config"]).read_text())
        self.model = REGISTRY[cfg["name"]].from_config(cfg)

    def predict(self, context, model_input, params=None) -> pd.DataFrame:
        """Một dòng mỗi (user, role), cùng các cột với `predictions.csv` của `geolife.run`."""
        _, pred = self.model.predict(model_input[POINT_COLS])
        return pred
