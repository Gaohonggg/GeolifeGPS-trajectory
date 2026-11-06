"""Chạy một model version trên một split và ghi kết quả.

    uv run python -m geolife.run --model stay_point --version 1 --split holdout

Ghi vào results/data_v<d>/<model>_v<k>/<split>/: predictions.csv (home / office) và metrics.json (chỉ số stay + mô tả output).
`dev` dùng khi tuning; `holdout` chỉ chạy một lần sau khi đã chốt tham số.
"""
from __future__ import annotations

import argparse
import json
import time

from . import io
from .evaluation import label_flags, prediction_summary, stay_metrics
from .models import load_model
from .paths import results_dir


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="stay_point")
    ap.add_argument("--version", type=int, required=True)
    ap.add_argument("--split", choices=["dev", "holdout", "all"], required=True)
    a = ap.parse_args(argv)

    model = load_model(a.model, a.version)
    dv = model.data_version
    users = io.split_users(dv, a.split)
    points = io.load_points(dv, users=users)
    t0 = time.perf_counter()
    stays, pred = model.predict(points)
    runtime = time.perf_counter() - t0
    flags = label_flags(points, io.load_labels(dv))
    metrics = {"model": model.run_name, "data_version": dv, "split": a.split, "users": len(users),
               "points": len(points), "params": model.params, "stay": stay_metrics(stays, points, flags),
               "home_office": prediction_summary(pred), "runtime_s": round(runtime, 1)}
    out = results_dir(dv, model.run_name) / a.split
    out.mkdir(parents=True, exist_ok=True)
    pred.to_csv(out / "predictions.csv", index=False)
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1, ensure_ascii=False))
    print(json.dumps(metrics, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
