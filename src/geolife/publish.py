"""Phát hành một version trong registry thành bản sao bất biến trên S3, để ECS task nạp model mà không cần Databricks.

    uv run python -m geolife.publish --version 4 [--bucket geolife-<account_id>-artifacts]

Bố cục: `models/<model>/v=<version>/model/…` (thư mục MLflow model) và `manifest.json`, ghi sau cùng bằng
conditional write. Có manifest thì version mới được coi là đã phát hành. Phát hành lại một version đã có manifest
thì so checksum: khớp thì không ghi gì, lệch thì dừng với lỗi (sửa model nghĩa là đăng ký version mới).

Cấu hình MLflow đọc từ môi trường / `.env` như `geolife.register`; credential AWS theo chuỗi mặc định (`AWS_PROFILE`).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

MANIFEST = "manifest.json"


class PublishError(Exception):
    pass


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def list_files(model_dir: Path) -> list[dict]:
    """Mọi file trong thư mục model, đường dẫn tương đối, sort để manifest ổn định."""
    return [{"path": p.relative_to(model_dir).as_posix(), "size": p.stat().st_size, "sha256": sha256(p)}
            for p in sorted(model_dir.rglob("*")) if p.is_file()]


def version_prefix(model_name: str, version: int) -> str:
    """`workspace.geolife.geolife_home_office`, 4 → `models/geolife_home_office/v=4/`."""
    return f"models/{model_name.rsplit('.', 1)[-1]}/v={version}/"


def _read_manifest(s3, bucket: str, key: str) -> dict | None:
    try:
        return json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise


def _check_same(existing: dict, files: list[dict], uri: str) -> None:
    old = {f["path"]: (f["size"], f["sha256"]) for f in existing["files"]}
    new = {f["path"]: (f["size"], f["sha256"]) for f in files}
    if old != new:
        diff = sorted(p for p in old.keys() | new.keys() if old.get(p) != new.get(p))
        raise PublishError(f"{uri} đã phát hành với nội dung khác (lệch ở {diff[:5]}); "
                           "không ghi đè version đã phát hành, hãy đăng ký version mới")


def publish_dir(s3, bucket: str, prefix: str, model_dir: Path, meta: dict) -> tuple[str, dict]:
    """Upload `model_dir` lên `s3://bucket/prefix`. Trả về ("published" | "already_published", manifest)."""
    uri = f"s3://{bucket}/{prefix}"
    files = list_files(model_dir)
    if not files:
        raise PublishError(f"{model_dir} không có file nào")

    existing = _read_manifest(s3, bucket, prefix + MANIFEST)
    if existing is not None:
        _check_same(existing, files, uri)
        return "already_published", existing

    # file của model trước; S3 kiểm SHA-256 phía server và từ chối nếu nội dung tới nơi bị sai
    for f in files:
        with (model_dir / f["path"]).open("rb") as body:
            s3.put_object(Bucket=bucket, Key=f"{prefix}model/{f['path']}", Body=body,
                          ChecksumSHA256=base64.b64encode(bytes.fromhex(f["sha256"])).decode())

    manifest = {**meta, "s3_uri": f"{uri}model", "published_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "files": files}
    try:
        s3.put_object(Bucket=bucket, Key=prefix + MANIFEST, IfNoneMatch="*", ContentType="application/json",
                      Body=json.dumps(manifest, indent=2, ensure_ascii=False).encode())
    except ClientError as e:
        if e.response["Error"]["Code"] not in ("PreconditionFailed", "412", "ConditionalRequestConflict"):
            raise
        # người khác vừa phát hành cùng version: chỉ chấp nhận nếu cùng nội dung
        existing = _read_manifest(s3, bucket, prefix + MANIFEST)
        _check_same(existing, files, uri)
        return "already_published", existing
    return "published", manifest


def registry_meta(client, model_name: str, version: int) -> dict:
    mv = client.get_model_version(model_name, str(version))
    run_tags = client.get_run(mv.run_id).data.tags if mv.run_id else {}
    return {
        "model_name": model_name,
        "version": version,
        "algorithm": mv.tags.get("algorithm"),
        "config_version": mv.tags.get("config_version"),
        "data_version": mv.tags.get("data_version"),
        "run_id": mv.run_id,
        "git_commit": run_tags.get("git_commit"),
    }


def default_bucket(session) -> str:
    account = session.client("sts").get_caller_identity()["Account"]
    return f"geolife-{account}-artifacts"


def main(argv=None):
    import mlflow.artifacts
    from mlflow.tracking import MlflowClient

    from .register import env, load_env_file

    ap = argparse.ArgumentParser()
    ap.add_argument("--version", type=int, required=True, help="version trong registry")
    ap.add_argument("--bucket", help="mặc định geolife-<account_id>-artifacts")
    a = ap.parse_args(argv)

    load_env_file()
    env("MLFLOW_REGISTRY_URI")
    model_name = env("MLFLOW_MODEL_NAME")
    session = boto3.Session()
    bucket = a.bucket or default_bucket(session)
    prefix = version_prefix(model_name, a.version)

    client = MlflowClient()
    meta = registry_meta(client, model_name, a.version)
    with tempfile.TemporaryDirectory() as tmp:
        model_dir = Path(mlflow.artifacts.download_artifacts(f"models:/{model_name}/{a.version}", dst_path=tmp))
        try:
            status, manifest = publish_dir(session.client("s3"), bucket, prefix, model_dir, meta)
        except PublishError as e:
            raise SystemExit(f"lỗi: {e}") from None

    # truy vết hai chiều: từ version trên registry ra bản sao trên S3
    client.set_model_version_tag(model_name, str(a.version), "s3_uri", manifest["s3_uri"])
    label = "đã phát hành" if status == "already_published" else "phát hành xong"
    print(f"{model_name} v{a.version}: {label} → {manifest['s3_uri']} ({len(manifest['files'])} file)")


if __name__ == "__main__":
    main()
