"""Đưa alias trên registry ra function Lambda: alias live chạy model của @champion, alias challenger chạy model
của @challenger, live chia `canary_weight` % request sang challenger.

    uv run python scripts/promote.py [--champion-only] [--auto-approve]

Function là một kệ; mỗi Lambda version là một hộp đã đóng, chứa một image và một registry version, không sửa được
và không bị xoá. Alias live / challenger là nhãn dán lên hộp.

1. Đổi @champion / @challenger thành số version (không có @champion thì dừng, AWS giữ nguyên); version nào chưa có
   bản phát hành trên S3 thì phát hành (geolife.publish).
2. `terraform apply` để cấu hình làm việc ($LATEST) theo code và cấu hình hiện tại (image mới nhất trong ECR, RAM,
   timeout…); cấu hình đổi thì Lambda đóng một hộp mới.
3. Nhãn live: tìm hộp có cùng cấu hình với $LATEST (trừ MODEL_URI) và chứa model của @champion, theo thứ tự: hộp
   đang dán live → hộp đang dán challenger → hộp mới nhất còn lại. Không có thì đóng hộp mới: đặt model của
   $LATEST trong `infra/app/models.auto.tfvars.json`, `terraform apply`, đọc số version vừa đóng.
4. Nhãn challenger: không có @challenger hoặc @challenger trùng @champion thì dán lên hộp của live (live nhận 100%);
   có thì tìm hoặc đóng hộp như bước 3.
5. Ghi hai nhãn vào tfvars và `terraform apply`. Tỉ lệ chia (`canary_weight`) nằm trong `canary.auto.tfvars`,
   promote không sửa.

Hộp cũ được dùng lại khi rollback hay huỷ canary mà không phải đóng mới, miễn là cùng image hiện tại.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections.abc import Callable
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


@dataclass(frozen=True)
class Labels:
    """Lambda version mà mỗi nhãn dán lên. `challenger == live`: không chia traffic."""
    live: int
    challenger: int


def alias_version(client: MlflowClient, model_name: str, alias: str) -> int | None:
    """Số version mà alias đang trỏ tới; None nếu alias chưa được gắn."""
    try:
        return int(client.get_model_version_by_alias(model_name, alias).version)
    except MlflowException:
        return None


def registry_targets(champion: int | None, challenger: int | None) -> tuple[int, int | None]:
    """Registry version cho hai nhãn. Không có @champion thì dừng; @challenger trùng @champion coi như không có."""
    if champion is None:
        raise SystemExit("registry chưa có alias @champion; AWS giữ nguyên")
    return champion, (None if challenger == champion else challenger)


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


def assign_labels(champion: int, challenger: int | None, current: Labels | None,
                  find: Callable[[int, list[int | None]], int | None], close: Callable[[int], int]) -> Labels:
    """Chọn hộp cho hai nhãn. `find(model_version, prefer)` tìm hộp cùng image hiện tại chứa model đó;
    `close(model_version)` đóng hộp mới và trả số version. Hộp của live chọn trước, nên khi phải đóng hai hộp
    thì hộp của @champion có số nhỏ hơn."""
    prefer = [current.live, current.challenger] if current else []

    def box_for(version: int) -> int:
        box = find(version, prefer)
        if box is None:
            box = close(version)
            print(f"đã đóng Lambda version {box} (registry v{version})")
        else:
            print(f"dùng lại Lambda version {box} (registry v{version})")
        return box

    live = box_for(champion)
    return Labels(live, live if challenger is None else box_for(challenger))


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


def current_labels(tfvars: dict) -> Labels | None:
    live = tfvars.get("live", {}).get("lambda_version")
    if live is None:
        return None
    challenger = (tfvars.get("challenger") or {}).get("lambda_version", live)
    return Labels(live, challenger)


def terraform(*args: str, capture: bool = False) -> str:
    out = subprocess.run(["terraform", f"-chdir={APP_DIR}", *args], check=True, text=True,
                         stdout=subprocess.PIPE if capture else None)
    return out.stdout if capture else ""


def apply(auto_approve: bool) -> None:
    terraform("apply", *(["-auto-approve"] if auto_approve else []))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--champion-only", action="store_true", help="bỏ qua @challenger: live nhận 100%%")
    ap.add_argument("--auto-approve", action="store_true", help="terraform apply không hỏi lại")
    a = ap.parse_args(argv)

    load_env_file()
    env("MLFLOW_REGISTRY_URI")
    model_name = env("MLFLOW_MODEL_NAME")
    client = MlflowClient()
    champion, challenger = registry_targets(
        alias_version(client, model_name, "champion"),
        None if a.champion_only else alias_version(client, model_name, "challenger"))
    print(f"@champion = v{champion}, @challenger = {f'v{challenger}' if challenger else '-'}")

    session = boto3.Session(region_name=os.environ.get("AWS_REGION"))
    bucket = publish.default_bucket(session)
    s3 = session.client("s3")
    for v in {champion, challenger} - {None}:
        ensure_published(model_name, v, bucket, s3)

    tfvars = read_tfvars()
    if not tfvars:
        # Lần deploy đầu, function chưa có: đóng version đầu tiên với model của @champion.
        # lambda_version null: stack app cho alias live trỏ vào version vừa đóng.
        tfvars = {"latest_model_version": champion, "live": {"lambda_version": None, "model_version": champion}}
        write_tfvars(tfvars)
        apply(a.auto_approve)
        tfvars["live"]["lambda_version"] = int(terraform("output", "-raw", "published_version", capture=True))
        write_tfvars(tfvars)
    apply(a.auto_approve)

    lam = session.client("lambda")
    latest_config = describe(lam, "$LATEST").config
    boxes = list_boxes(lam)

    def find(version: int, prefer: list[int | None]) -> int | None:
        return find_box(boxes, latest_config, model_uri(bucket, model_name, version), prefer)

    def close(version: int) -> int:
        if tfvars["latest_model_version"] == version:
            # $LATEST đã chứa model này với cấu hình hiện tại mà không có hộp nào khớp: Lambda không đóng thêm
            # khi cấu hình không đổi, nên không có cách đóng hộp ở đây.
            raise SystemExit(f"$LATEST đã chứa v{version} nhưng không có Lambda version nào khớp; kiểm tra function")
        # Hai nhãn giữ hộp cũ trong lúc đóng.
        tfvars["latest_model_version"] = version
        write_tfvars(tfvars)
        apply(a.auto_approve)
        box = int(terraform("output", "-raw", "published_version", capture=True))
        boxes.append(describe(lam, str(box)))
        return box

    labels = assign_labels(champion, challenger, current_labels(tfvars), find, close)

    tfvars["live"] = {"lambda_version": labels.live, "model_version": champion}
    tfvars["challenger"] = {"lambda_version": labels.challenger,
                            "model_version": champion if challenger is None else challenger}
    write_tfvars(tfvars)
    apply(a.auto_approve)
    if labels.challenger == labels.live:
        print(f"live → Lambda version {labels.live} (registry v{champion}) 100%; challenger trùng live")
    else:
        print(f"live → Lambda version {labels.live} (registry v{champion}), chia canary_weight % sang "
              f"challenger → Lambda version {labels.challenger} (registry v{challenger})")


if __name__ == "__main__":
    main()
