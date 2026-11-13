"""Đăng ký model version đã eval vào MLflow Model Registry.

    uv run python -m geolife.register --model dbscan --version 3
    uv run python -m geolife.register        # mọi version chưa đăng ký

Mọi thuật toán chung một registered model (`MLFLOW_MODEL_NAME`); tag `algorithm`, `config_version` của mỗi version
cho biết nó ứng với config nào. Cấu hình MLflow đọc từ môi trường, thiếu thì lấy từ `.env`.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from importlib.metadata import version as pkg_version

import mlflow
from mlflow.exceptions import MlflowException
from mlflow.models import infer_signature
from mlflow.tracking import MlflowClient

from . import io
from .mlflow_model import HomeOfficeModel
from .models import REGISTRY, load_config
from .models.base import POINT_COLS, config_path
from .paths import ROOT, results_dir

SIGNATURE_USER = 5   # có cả home và office
# khớp [project].dependencies trong pyproject.toml
REQUIREMENTS = ["holidays", "numba", "numpy", "pandas", "pyyaml", "scikit-learn", "scipy", "timezonefinder", "tzdata"]


def load_env_file(path=ROOT / ".env") -> None:
    """Nạp `.env` cho các biến chưa có trong môi trường."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.lstrip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip())


def env(key: str) -> str:
    if not os.environ.get(key):
        raise SystemExit(f"chưa đặt {key} (thêm vào .env, xem .env.example)")
    return os.environ[key]


def flatten(d: dict, prefix: str = "") -> dict:
    """{"a": {"b": 1}} → {"a.b": 1}."""
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten(v, f"{key}."))
        else:
            out[key] = v
    return out


def git_info() -> dict[str, str]:
    def git(*args):
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()
    return {"git_commit": git("rev-parse", "HEAD"), "git_dirty": str(bool(git("status", "--porcelain")))}


def load_metrics(name: str, version: int, data_version: int, split: str) -> dict | None:
    path = results_dir(data_version, f"{name}_v{version}") / split / "metrics.json"
    return json.loads(path.read_text()) if path.exists() else None


def main_metrics(m: dict) -> dict[str, float]:
    """Chỉ số chính trên holdout (docs/evaluation.md), bỏ chỉ số null."""
    stay, ho = m["stay"], m["home_office"]
    out = {
        "stays_per_day": stay["stays_per_day"],
        "fake_share": stay["fake_share"],
        "fragment_share": stay["fragment_share"],
        "long_stays": stay["long_stays"],
        **{f"{role}_coverage": ho[role]["predicted"] / ho[role]["users"] for role in ("home", "office")},
    }
    return {k: float(v) for k, v in out.items() if v is not None}


def registered(client: MlflowClient) -> dict[tuple[str, int], str]:
    """(thuật toán, config version) → version trong registry."""
    name = env("MLFLOW_MODEL_NAME")
    try:
        found = client.search_model_versions(f"name='{name}'")
    except MlflowException:
        return {}
    # Unity Catalog không trả tag khi search
    versions = [client.get_model_version(name, v.version) for v in found]
    return {(v.tags["algorithm"], int(v.tags["config_version"])): str(v.version)
            for v in versions if "algorithm" in v.tags and "config_version" in v.tags}


def config_versions(name: str) -> list[int]:
    return sorted(int(p.name.removeprefix("v_")) for p in (ROOT / "models_tuning" / name).glob("v_*"))


def signature(cfg: dict):
    """Schema input / output, suy ra từ một user thật."""
    points = io.load_points(cfg["data_version"], users=[SIGNATURE_USER])[POINT_COLS]
    points["user"] = points["user"].astype("int64")   # long: nhận cả input int16 / int32
    _, pred = REGISTRY[cfg["name"]].from_config(cfg).predict(points)
    return infer_signature(points, pred)


def register(name: str, version: int, client: MlflowClient) -> str:
    """Trả về version trong registry; đã đăng ký thì bỏ qua."""
    model_name = env("MLFLOW_MODEL_NAME")
    done = registered(client)
    if (name, version) in done:
        print(f"{name} v{version}: đã có (registry version {done[name, version]}), bỏ qua")
        return done[name, version]
    missing = [v for v in config_versions(name) if v < version and (name, v) not in done]
    if missing:
        raise SystemExit(f"{name}: phải đăng ký v{missing[0]} trước v{version}")

    cfg = load_config(name, version)
    dv = cfg["data_version"]
    holdout = load_metrics(name, version, dv, "holdout")
    if holdout is not None and holdout["params"] != cfg["params"]:
        raise SystemExit(f"{name} v{version}: kết quả holdout không chạy bằng tham số hiện tại của config, chạy lại eval")

    tags = {"algorithm": name, "config_version": str(version), "data_version": str(dv)}
    mlflow.set_experiment(env("MLFLOW_EXPERIMENT_NAME"))
    with mlflow.start_run(run_name=f"{name}_v{version}"):
        mlflow.set_tags({**tags, **git_info()})
        mlflow.log_params({k: str(v) for k, v in flatten(cfg["params"]).items()})
        if holdout is not None:
            mlflow.log_metrics(main_metrics(holdout))
        for split in ("dev", "holdout"):
            path = results_dir(dv, f"{name}_v{version}") / split / "metrics.json"
            if path.exists():
                mlflow.log_artifact(str(path), artifact_path=f"metrics/{split}")
        info = mlflow.pyfunc.log_model(
            name="model",
            python_model=HomeOfficeModel(),
            artifacts={"config": str(config_path(name, version))},
            code_paths=[str(ROOT / "src" / "geolife")],
            pip_requirements=[f"{p}=={pkg_version(p)}" for p in REQUIREMENTS],
            signature=signature(cfg),
            metadata={"algorithm": name, "version": version, "data_version": dv},
        )
        mv = mlflow.register_model(info.model_uri, model_name, tags=tags)
    print(f"{name} v{version}: đã đăng ký thành {model_name} version {mv.version} (run {info.run_id})")
    return str(mv.version)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Không truyền --model / --version: đăng ký mọi version chưa có.")
    ap.add_argument("--model", choices=list(REGISTRY))
    ap.add_argument("--version", type=int)
    a = ap.parse_args(argv)
    if bool(a.model) != bool(a.version):
        ap.error("--model và --version phải đi cùng nhau")

    load_env_file()
    env("MLFLOW_TRACKING_URI")   # thiếu thì MLflow ghi ra ./mlruns
    client = MlflowClient()
    if a.model:
        register(a.model, a.version, client)
        return
    # theo thứ tự REGISTRY, rồi theo version
    for name in REGISTRY:
        for v in config_versions(name):
            register(name, v, client)


if __name__ == "__main__":
    main()
