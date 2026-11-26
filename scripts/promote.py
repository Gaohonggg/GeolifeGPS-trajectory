"""Đưa alias trên registry ra function Lambda: alias live chạy model của @champion.

    uv run python scripts/promote.py [--champion-only] [--auto-approve]

1. Đổi @champion / @challenger thành số version; version nào chưa có bản phát hành trên S3 thì phát hành (geolife.publish).
2. `terraform apply` để cấu hình làm việc ($LATEST) theo code và cấu hình hiện tại (image mới nhất trong ECR, RAM,
   timeout…); cấu hình đổi thì Lambda đóng một version mới.
3. Tìm Lambda version có cùng cấu hình với $LATEST (trừ MODEL_URI) và chứa model của @champion, theo thứ tự:
   version đang gắn alias live → version mới nhất. Không có thì đóng version mới: đặt model của $LATEST là @champion
   trong `infra/app/models.auto.tfvars.json`, `terraform apply`, đọc số version vừa đóng.
4. Ghi version đó vào `live` trong tfvars và `terraform apply` để alias live trỏ vào nó.

Lambda version bất biến và không bị xoá, nên version cũ được dùng lại khi rollback mà không phải đóng mới.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import dataclass

import boto3
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient

from geolife import publish
from geolife.paths import ROOT
from geolife.register import env, load_env_file

FUNCTION = "geolife-api"
APP_DIR = ROOT / "infra" / "app"
TFVARS = APP_DIR / "models.auto.tfvars.json"


@dataclass(frozen=True)
class Box:
    """Một Lambda version: model nó chứa và phần cấu hình còn lại (image, RAM, timeout, biến môi trường khác)."""
    lambda_version: str
    config: str
    model_uri: str


def alias_version(client: MlflowClient, model_name: str, alias: str) -> int | None:
    """Số version mà alias đang trỏ tới; None nếu alias chưa được gắn."""
    try:
        return int(client.get_model_version_by_alias(model_name, alias).version)
    except MlflowException:
        return None


def ensure_published(model_name: str, version: int, bucket: str, s3) -> None:
    """Phát hành version lên S3 nếu chưa có manifest (manifest được ghi sau cùng, nên có manifest là đã đủ file)."""
    key = publish.version_prefix(model_name, version) + publish.MANIFEST
    try:
        s3.head_object(Bucket=bucket, Key=key)
    except s3.exceptions.ClientError as e:
        if e.response["Error"]["Code"] not in ("404", "NoSuchKey"):
            raise
        print(f"v{version} chưa có trên S3, phát hành")
        publish.main(["--version", str(version), "--bucket", bucket])


def model_uri(bucket: str, model_name: str, version: int) -> str:
    """Giá trị MODEL_URI của function cho một registry version; trùng với cách stack app dựng biến này."""
    return f"s3://{bucket}/{publish.version_prefix(model_name, version)}model"


def find_box(boxes: list[Box], config: str, uri: str, prefer: list[int | None]) -> int | None:
    """Lambda version có cấu hình `config` và chứa model `uri`; ưu tiên version trong `prefer` theo thứ tự,
    sau đó version mới nhất."""
    matches = {int(b.lambda_version) for b in boxes
               if b.lambda_version != "$LATEST" and b.config == config and b.model_uri == uri}
    for v in prefer:
        if v in matches:
            return v
    return max(matches, default=None)


def describe(lam, qualifier: str) -> Box:
    """Cấu hình của một Lambda version (hoặc $LATEST), tách MODEL_URI ra khỏi phần còn lại."""
    fn = lam.get_function(FunctionName=FUNCTION, Qualifier=qualifier)
    c = fn["Configuration"]
    env_vars = dict(c.get("Environment", {}).get("Variables", {}))
    uri = env_vars.pop("MODEL_URI", "")
    config = {
        "image": fn["Code"].get("ResolvedImageUri"),
        "image_config": c.get("ImageConfigResponse", {}).get("ImageConfig"),
        "architectures": c.get("Architectures"),
        "memory": c["MemorySize"],
        "timeout": c["Timeout"],
        "ephemeral_storage": c.get("EphemeralStorage"),
        "role": c["Role"],
        "env": env_vars,
        "logging": c.get("LoggingConfig"),
    }
    return Box(qualifier, json.dumps(config, sort_keys=True), uri)


def list_boxes(lam) -> list[Box]:
    """Mọi Lambda version đã đóng của function (bỏ $LATEST)."""
    versions = [v["Version"] for page in lam.get_paginator("list_versions_by_function").paginate(
        FunctionName=FUNCTION) for v in page["Versions"] if v["Version"] != "$LATEST"]
    return [describe(lam, v) for v in versions]


def read_tfvars() -> dict:
    return json.loads(TFVARS.read_text()) if TFVARS.exists() else {}


def write_tfvars(tfvars: dict) -> None:
    TFVARS.write_text(json.dumps(tfvars, indent=2) + "\n")


def terraform(*args: str, capture: bool = False) -> str:
    out = subprocess.run(["terraform", f"-chdir={APP_DIR}", *args], check=True, text=True,
                         stdout=subprocess.PIPE if capture else None)
    return out.stdout if capture else ""


def apply(auto_approve: bool) -> None:
    terraform("apply", *(["-auto-approve"] if auto_approve else []))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--champion-only", action="store_true", help="bỏ qua @challenger")
    ap.add_argument("--auto-approve", action="store_true", help="terraform apply không hỏi lại")
    a = ap.parse_args(argv)

    load_env_file()
    env("MLFLOW_REGISTRY_URI")
    model_name = env("MLFLOW_MODEL_NAME")
    client = MlflowClient()
    champion = alias_version(client, model_name, "champion")
    if champion is None:
        raise SystemExit(f"{model_name} chưa có alias @champion; AWS giữ nguyên")
    challenger = None if a.champion_only else alias_version(client, model_name, "challenger")
    print(f"@champion = v{champion}, @challenger = {f'v{challenger}' if challenger else '-'}")

    session = boto3.Session(region_name=os.environ.get("AWS_REGION"))
    bucket = publish.default_bucket(session)
    s3 = session.client("s3")
    for v in {champion, challenger} - {None}:
        ensure_published(model_name, v, bucket, s3)

    uri = model_uri(bucket, model_name, champion)
    tfvars = read_tfvars()
    if not tfvars:
        # Lần deploy đầu, function chưa có: đóng version đầu tiên với model của @champion.
        # lambda_version null: stack app cho alias live trỏ vào version vừa đóng.
        tfvars = {"latest_model_version": champion, "live": {"lambda_version": None, "model_version": champion}}
        write_tfvars(tfvars)
        apply(a.auto_approve)
        box = int(terraform("output", "-raw", "published_version", capture=True))
        print(f"đã đóng Lambda version {box}")
    else:
        apply(a.auto_approve)
        lam = session.client("lambda")
        latest = describe(lam, "$LATEST")
        box = find_box(list_boxes(lam), latest.config, uri, prefer=[tfvars["live"].get("lambda_version")])
        if box is None:
            print(f"chưa có Lambda version chứa v{champion} với cấu hình hiện tại, đóng version mới")
            # Alias live giữ version cũ trong lúc đóng.
            tfvars["latest_model_version"] = champion
            write_tfvars(tfvars)
            apply(a.auto_approve)
            box = int(terraform("output", "-raw", "published_version", capture=True))
            print(f"đã đóng Lambda version {box}")
        else:
            print(f"dùng lại Lambda version {box}")

    tfvars["live"] = {"lambda_version": box, "model_version": champion}
    write_tfvars(tfvars)
    apply(a.auto_approve)
    print(f"live → Lambda version {box} (registry v{champion})")


if __name__ == "__main__":
    main()
