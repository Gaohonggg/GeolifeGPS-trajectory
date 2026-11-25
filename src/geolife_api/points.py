"""Nguồn điểm GPS của API: bản dựng `data/serving/v_<n>/` trên S3 hoặc ở thư mục local.

Bố cục (do `geolife_api.export_points` dựng):

    points/user=<id>.parquet   điểm của một user, sort theo ts_utc, row group có thống kê min / max của ts_utc
    manifest.json              mô tả bản dựng; có file này thì bản dựng mới hoàn chỉnh

Đọc parquet qua file object có `seek`: pyarrow đọc footer, chọn các row group có `ts_utc` giao với [start, end) theo
thống kê, rồi chỉ tải các byte của những row group đó. Trên S3 mỗi lần đọc là một GET có header `Range`; pyarrow
gộp các đoạn liền nhau (`pre_buffer`) nên mỗi request đọc một user tốn khoảng hai GET (footer và dữ liệu).

S3 đọc bằng boto3 để dùng chung chuỗi credential với các lệnh AWS khác của repo; AWS SDK C++ trong
`pyarrow.fs.S3FileSystem` không đọc được credential `login_session` do `aws login` tạo.

Module này không import `geolife`: image của API chỉ chứa `geolife_api`.
"""
from __future__ import annotations

import io
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from .service import DataUnavailable

MANIFEST = "manifest.json"


def user_file(user_id: int) -> str:
    """Đường dẫn file điểm của một user, tương đối với gốc bản dựng."""
    return f"points/user={user_id}.parquet"


class S3ObjectFile(io.RawIOBase):
    """Một object S3 dạng file chỉ đọc, có `seek`; mỗi lần `readinto` là một GET theo `Range`."""

    def __init__(self, s3, bucket: str, key: str, size: int):
        self.s3, self.bucket, self.key, self.size = s3, bucket, key, size
        self.pos = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self.pos, io.SEEK_END: self.size}[whence]
        self.pos = base + offset
        return self.pos

    def readinto(self, buf) -> int:
        n = min(len(buf), self.size - self.pos)
        if n <= 0:
            return 0
        body = self.s3.get_object(Bucket=self.bucket, Key=self.key,
                                  Range=f"bytes={self.pos}-{self.pos + n - 1}")["Body"].read()
        buf[:len(body)] = body
        self.pos += len(body)
        return len(body)


class S3PointStore:
    """`service.PointStore` trên `s3://<bucket>/<prefix>` hoặc một thư mục local (đường dẫn thường)."""

    def __init__(self, uri: str, s3=None):
        if uri.startswith("s3://"):
            bucket, _, prefix = uri.removeprefix("s3://").partition("/")
            prefix = prefix.strip("/")
            self.bucket = bucket
            self.prefix = f"{prefix}/" if prefix else ""
            if s3 is None:
                import boto3

                s3 = boto3.client("s3")
            self.s3 = s3
            self.root = None
        else:
            self.root = Path(uri).resolve()
            self.s3 = None

    # ---- truy cập file, giống nhau cho S3 và local ----

    def _size(self, name: str) -> int | None:
        """Kích thước file, None nếu không có. Lỗi khác (mất mạng, thiếu quyền) → DataUnavailable."""
        if self.root is not None:
            p = self.root / name
            return p.stat().st_size if p.is_file() else None
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            return self.s3.head_object(Bucket=self.bucket, Key=self.prefix + name)["ContentLength"]
        except ClientError as e:
            # không có s3:ListBucket thì S3 trả 403 cho object không tồn tại, không phân biệt được với lỗi quyền
            if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                return None
            raise DataUnavailable(f"cannot read {self.prefix + name}") from e
        except BotoCoreError as e:
            raise DataUnavailable(f"cannot read {self.prefix + name}") from e

    def _open(self, name: str, size: int):
        if self.root is not None:
            return (self.root / name).open("rb")
        return S3ObjectFile(self.s3, self.bucket, self.prefix + name, size)

    def _read_all(self, name: str) -> bytes:
        """Cả file trong một lần đọc (một GET trên S3)."""
        if self.root is not None:
            return (self.root / name).read_bytes()
        return self.s3.get_object(Bucket=self.bucket, Key=self.prefix + name)["Body"].read()

    # ---- PointStore ----

    def ping(self) -> bool:
        """Đọc được manifest.json của bản dựng."""
        try:
            json.loads(self._read_all(MANIFEST))
            return True
        except Exception:
            return False

    def user_exists(self, user_id: int) -> bool:
        return self._size(user_file(user_id)) is not None

    def fetch_points(self, user_id: int, start: datetime | None = None, end: datetime | None = None) -> pd.DataFrame:
        """Điểm trong [start, end), sort theo ts_utc (naive UTC); cột theo geolife.models.base.POINT_COLS."""
        name = user_file(user_id)
        size = self._size(name)
        if size is None:
            raise KeyError(user_id)
        lo, hi = _naive_utc(start), _naive_utc(end)
        try:
            with self._open(name, size) as f:
                pf = pq.ParquetFile(f, pre_buffer=True)
                groups = row_groups_in_range(pf.metadata, lo, hi)
                table = pf.read_row_groups(groups) if groups else pf.schema_arrow.empty_table()
        except (OSError, pa.ArrowException) as e:
            raise DataUnavailable(f"cannot read {name}") from e
        if lo is not None:
            table = table.filter(pc.greater_equal(table["ts_utc"], pa.scalar(lo, pa.timestamp("us"))))
        if hi is not None:
            table = table.filter(pc.less(table["ts_utc"], pa.scalar(hi, pa.timestamp("us"))))
        return table.to_pandas()


def _naive_utc(t: datetime | None) -> datetime | None:
    """`service.parse_time` đã đổi sang UTC; cột ts_utc trong parquet không mang múi giờ."""
    return None if t is None else t.replace(tzinfo=None)


def row_groups_in_range(meta: pq.FileMetaData, lo: datetime | None, hi: datetime | None) -> list[int]:
    """Các row group có ts_utc giao với [lo, hi), theo min / max trong footer."""
    col = meta.schema.names.index("ts_utc")
    out = []
    for i in range(meta.num_row_groups):
        st = meta.row_group(i).column(col).statistics
        if st is None or not st.has_min_max:
            out.append(i)    # không có thống kê thì phải đọc
            continue
        if (hi is None or st.min < hi) and (lo is None or st.max >= lo):
            out.append(i)
    return out
