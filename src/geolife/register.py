"""Đăng ký model version đã eval vào MLflow Model Registry.

    uv run python -m geolife.register --model dbscan --version 3
    uv run python -m geolife.register     # mọi version chưa đăng ký

Mọi thuật toán chung một registered model (`MODEL_NAME`), nên API chỉ cần đổi version trong
`models:/geolife_home_office/<version>`. Version của registry là số thứ tự đăng ký; version nào ứng với thuật toán và
config nào thì xem tag `algorithm`, `config_version` của version đó (hoặc metadata của model).

Quy trình cho một model version mới: notebook `models_tuning/<tên>/v_<k>/tuning.ipynb` chọn tham số, rồi ô cuối của
notebook eval holdout (`geolife.run`) và gọi lệnh này. Lệnh từ chối nếu kết quả holdout không chạy bằng đúng tham số
trong config (config bị sửa sau khi eval). Version đã đăng ký thì bỏ qua; cùng một thuật toán phải đăng ký theo thứ tự v_1, v_2, … Thuật toán mới chỉ cần có
trong `models.REGISTRY` và có thư mục `models_tuning/<tên>/`, không phải sửa file này.

Mỗi version gắn với một run ghi: tham số của config, chỉ số chính trên holdout (`main_metrics`), metrics.json của dev
và holdout, `data_version`, git commit.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from importlib.metadata import version as pkg_version

import mlflow
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient

from .mlflow_model import HomeOfficeModel
from .models import REGISTRY, load_config
from .models.base import config_path
from .paths import ROOT, results_dir

MODEL_NAME = "geolife_home_office"
LOCAL_MLFLOW = "http://localhost:5001"
EXPERIMENT = os.environ.get("MLFLOW_EXPERIMENT_NAME", MODEL_NAME)
# Thư viện mà code thuật toán cần khi nạp lại model (đồng bộ với [project].dependencies trong pyproject.toml)
REQUIREMENTS = ["holidays", "numba", "numpy", "pandas", "pyyaml", "scikit-learn", "scipy", "timezonefinder", "tzdata"]


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
    """Chỉ số chính trên holdout (docs/evaluation.md): stay (tỉ lệ tạo stay, stay giả, phân mảnh, stay dài) và độ phủ
    home / office. Chỉ số không đo được (null) thì không ghi. metrics.json đầy đủ của dev và holdout đính kèm vào run."""
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
    """(thuật toán, config version) → version trong registry, đọc từ tag của các version đã đăng ký."""
    try:
        versions = client.search_model_versions(f"name='{MODEL_NAME}'")
    except MlflowException:
        return {}
    return {(v.tags["algorithm"], int(v.tags["config_version"])): str(v.version)
            for v in versions if "algorithm" in v.tags and "config_version" in v.tags}


def config_versions(name: str) -> list[int]:
    return sorted(int(p.name.removeprefix("v_")) for p in (ROOT / "models_tuning" / name).glob("v_*"))


def register(name: str, version: int, client: MlflowClient) -> str:
    """Đăng ký `name` v_`version` (đã eval holdout); trả về version trong registry."""
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
    mlflow.set_experiment(EXPERIMENT)
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
            metadata={"algorithm": name, "version": version, "data_version": dv},
        )
        mv = mlflow.register_model(info.model_uri, MODEL_NAME, tags=tags)
    print(f"{name} v{version}: đã đăng ký thành {MODEL_NAME} version {mv.version} (run {info.run_id})")
    return str(mv.version)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Không truyền --model / --version: đăng ký mọi version chưa có.")
    ap.add_argument("--model", choices=list(REGISTRY))
    ap.add_argument("--version", type=int)
    a = ap.parse_args(argv)
    if bool(a.model) != bool(a.version):
        ap.error("--model và --version phải đi cùng nhau")

    # mặc định là MLflow của stack local (docker/compose.yaml); đặt MLFLOW_TRACKING_URI để dùng server khác
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", LOCAL_MLFLOW))
    client = MlflowClient()
    if a.model:
        register(a.model, a.version, client)
        return
    # thứ tự của REGISTRY (thuật toán phát triển trước đăng ký trước), trong mỗi thuật toán theo version
    for name in REGISTRY:
        for v in config_versions(name):
            register(name, v, client)


if __name__ == "__main__":
    main()
