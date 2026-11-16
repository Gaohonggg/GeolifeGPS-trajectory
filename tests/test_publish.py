"""Phát hành model lên S3: ghi một lần, phát hành lại không ghi gì, lệch checksum thì dừng."""
from __future__ import annotations

import base64
import hashlib
import io
import json

import pytest
from botocore.exceptions import ClientError

from geolife.publish import MANIFEST, PublishError, publish_dir, version_prefix

BUCKET, PREFIX = "bucket", "models/geolife_home_office/v=4/"
META = {"model_name": "workspace.geolife.geolife_home_office", "version": 4}


def _error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code}}, "op")


class FakeS3:
    """Đủ phần của S3 mà publish_dir dùng: get_object, put_object có IfNoneMatch và ChecksumSHA256."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.puts: list[str] = []

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise _error("NoSuchKey")
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, Bucket, Key, Body, IfNoneMatch=None, ChecksumSHA256=None, **_):
        data = Body if isinstance(Body, bytes) else Body.read()
        if IfNoneMatch == "*" and Key in self.objects:
            raise _error("PreconditionFailed")
        if ChecksumSHA256 is not None and ChecksumSHA256 != base64.b64encode(hashlib.sha256(data).digest()).decode():
            raise _error("BadDigest")
        self.objects[Key] = data
        self.puts.append(Key)


@pytest.fixture
def model_dir(tmp_path):
    d = tmp_path / "model"
    (d / "artifacts").mkdir(parents=True)
    (d / "MLmodel").write_text("flavors: {}\n")
    (d / "artifacts" / "config.yaml").write_text("eps: 50\n")
    return d


def test_version_prefix():
    assert version_prefix("workspace.geolife.geolife_home_office", 4) == PREFIX


def test_first_publish_writes_files_then_manifest(model_dir):
    s3 = FakeS3()
    status, manifest = publish_dir(s3, BUCKET, PREFIX, model_dir, META)
    assert status == "published"
    assert s3.puts[-1] == PREFIX + MANIFEST                       # manifest ghi sau cùng
    assert set(s3.puts[:-1]) == {PREFIX + "model/MLmodel", PREFIX + "model/artifacts/config.yaml"}
    saved = json.loads(s3.objects[PREFIX + MANIFEST])
    assert saved["s3_uri"] == f"s3://{BUCKET}/{PREFIX}model"
    assert saved["version"] == 4
    assert {f["path"] for f in saved["files"]} == {"MLmodel", "artifacts/config.yaml"}


def test_republish_same_content_writes_nothing(model_dir):
    s3 = FakeS3()
    publish_dir(s3, BUCKET, PREFIX, model_dir, META)
    n = len(s3.puts)
    status, _ = publish_dir(s3, BUCKET, PREFIX, model_dir, META)
    assert status == "already_published"
    assert len(s3.puts) == n


def test_republish_different_content_fails(model_dir):
    s3 = FakeS3()
    publish_dir(s3, BUCKET, PREFIX, model_dir, META)
    (model_dir / "artifacts" / "config.yaml").write_text("eps: 60\n")
    n = len(s3.puts)
    with pytest.raises(PublishError, match="artifacts/config.yaml"):
        publish_dir(s3, BUCKET, PREFIX, model_dir, META)
    assert len(s3.puts) == n


def test_files_without_manifest_are_republished(model_dir):
    """Lần trước dừng giữa chừng (có file, chưa có manifest): chưa coi là đã phát hành, ghi lại từ đầu."""
    s3 = FakeS3()
    s3.objects[PREFIX + "model/MLmodel"] = b"partial"
    status, _ = publish_dir(s3, BUCKET, PREFIX, model_dir, META)
    assert status == "published"
    assert s3.objects[PREFIX + "model/MLmodel"] == (model_dir / "MLmodel").read_bytes()


def test_concurrent_publish_of_same_content_is_accepted(model_dir):
    """Manifest xuất hiện giữa lúc kiểm và lúc ghi: conditional write từ chối, nội dung khớp thì chấp nhận."""
    s3 = FakeS3()
    _, manifest = publish_dir(FakeS3(), BUCKET, PREFIX, model_dir, META)
    real_get = s3.get_object
    calls = {"n": 0}

    def get_object(Bucket, Key):
        calls["n"] += 1
        if Key == PREFIX + MANIFEST and calls["n"] == 1:
            s3.objects[Key] = json.dumps(manifest).encode()   # người khác ghi ngay sau lần đọc đầu
            raise _error("NoSuchKey")
        return real_get(Bucket, Key)

    s3.get_object = get_object
    status, _ = publish_dir(s3, BUCKET, PREFIX, model_dir, META)
    assert status == "already_published"
