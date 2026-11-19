"""Đổi alias trên registry thành model version của hai slot API, ghi infra/serving/models.auto.tfvars.json.

    uv run python scripts/promote.py [--champion-only]

Version nào của @champion / @challenger chưa có bản phát hành trên S3 thì phát hành trước (geolife.publish).
Quy tắc xếp slot (live slot phục vụ @champion, slot còn lại chạy @challenger):
  - chưa slot nào chạy @champion: blue nhận @champion và thành live slot
  - slot còn lại đang chạy đúng @champion (canary đã lên 100%): slot đó thành live slot, slot cũ dừng
  - có @challenger khác @champion: slot còn lại nhận @challenger; canary_weight về 0 khi version của slot đổi
  - không có @challenger, hoặc --champion-only: slot còn lại dừng, canary_weight = 0

Task chạy theo số version thay vì alias, nên đổi alias không ảnh hưởng task đang chạy cho tới lần promote sau.
File tfvars được commit, nên git log của nó là lịch sử deploy.
"""
from __future__ import annotations

import argparse
import json
import os

import boto3
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient

from geolife import publish
from geolife.paths import ROOT
from geolife.register import env, load_env_file

TFVARS = ROOT / "infra" / "serving" / "models.auto.tfvars.json"
DEFAULT = {"blue_model_version": None, "green_model_version": None, "live_slot": "blue", "canary_weight": 0}


def other(slot: str) -> str:
    """Slot còn lại của cặp blue / green."""
    return "green" if slot == "blue" else "blue"


def assign(current: dict, champion: int, challenger: int | None) -> dict:
    """Trạng thái mới của hai slot, theo quy tắc ở docstring của module."""
    state = {**DEFAULT, **current}
    version = {s: state[f"{s}_model_version"] for s in ("blue", "green")}
    live = state["live_slot"]
    weight = state["canary_weight"]

    if version[live] != champion:
        if version[other(live)] == champion:          # canary đã lên 100%: slot còn lại thành live slot
            version[live] = None
            live = other(live)
        else:                                         # lần đầu, hoặc @champion là version chưa chạy ở slot nào
            live = "blue"
            version = {"blue": champion, "green": None}
        weight = 0

    if challenger is not None and challenger != champion:
        if version[other(live)] != challenger:
            weight = 0
        version[other(live)] = challenger
    else:
        version[other(live)] = None
        weight = 0

    return {"blue_model_version": version["blue"], "green_model_version": version["green"],
            "live_slot": live, "canary_weight": weight}


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


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--champion-only", action="store_true", help="bỏ qua @challenger")
    a = ap.parse_args(argv)

    load_env_file()
    env("MLFLOW_REGISTRY_URI")
    model_name = env("MLFLOW_MODEL_NAME")
    client = MlflowClient()
    champion = alias_version(client, model_name, "champion")
    if champion is None:
        raise SystemExit(f"{model_name} chưa có alias @champion")
    challenger = None if a.champion_only else alias_version(client, model_name, "challenger")

    session = boto3.Session(region_name=os.environ.get("AWS_REGION"))
    bucket = publish.default_bucket(session)
    s3 = session.client("s3")
    for v in {champion, challenger} - {None}:
        ensure_published(model_name, v, bucket, s3)

    current = json.loads(TFVARS.read_text()) if TFVARS.exists() else {}
    new = assign(current, champion, challenger)
    TFVARS.write_text(json.dumps(new, indent=2) + "\n")
    print(f"@champion = v{champion}, @challenger = {f'v{challenger}' if challenger else '-'}")
    print(json.dumps(new, indent=2))


if __name__ == "__main__":
    main()
