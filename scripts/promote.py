"""Đổi alias trên registry thành số model version và phát hành lên S3 version nào chưa có.

    uv run python scripts/promote.py [--champion-only]

Version nào của @champion / @challenger chưa có bản phát hành trên S3 thì phát hành trước (geolife.publish).
"""
from __future__ import annotations

import argparse
import os

import boto3
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient

from geolife import publish
from geolife.register import env, load_env_file


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

    print(f"@champion = v{champion}, @challenger = {f'v{challenger}' if challenger else '-'}")


if __name__ == "__main__":
    main()
