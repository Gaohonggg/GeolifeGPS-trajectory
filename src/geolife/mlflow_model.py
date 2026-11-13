"""Bọc model version thành MLflow pyfunc. Mỗi version mang theo code `geolife` (`code_paths`) và `config.yaml`, nên
nơi nạp model không cần cài package."""
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
        """Một dòng mỗi (user, role), cùng cột với `predictions.csv`."""
        _, pred = self.model.predict(model_input[POINT_COLS])
        return pred
