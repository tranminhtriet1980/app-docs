"""Lưu trữ đối tượng (MinIO/S3-compatible) cho document upload + export file.

CHỈ dùng khi settings.s3_enabled (S3_ENDPOINT_URL có giá trị) — mọi hàm ở đây là thao tác
CHẶN (blocking, boto3 không có bản async chính thức), gọi từ code async phải bọc
`await asyncio.to_thread(...)`, giống cách backend/app/services/notify.py bọc SMTP.

Quy ước phân biệt file MỚI (MinIO) và file CŨ (đĩa cục bộ, từ trước khi bật S3): file_path
lưu trong DB là "s3://<bucket>/<key>" cho file MinIO, hoặc đường dẫn đĩa tuyệt đối cho file
cũ — không cần thêm cột DB, chỉ cần so tiền tố (xem is_s3_uri).
"""

import tempfile
from pathlib import Path

from app.config import settings

S3_URI_PREFIX = "s3://"


def is_s3_uri(file_path: str) -> bool:
    return (file_path or "").startswith(S3_URI_PREFIX)


def make_s3_uri(key: str) -> str:
    return f"{S3_URI_PREFIX}{settings.s3_bucket}/{key}"


def parse_s3_uri(uri: str) -> tuple[str, str]:
    """"s3://bucket/a/b/c.pdf" -> ("bucket", "a/b/c.pdf")."""
    rest = uri[len(S3_URI_PREFIX) :]
    bucket, _, key = rest.partition("/")
    return bucket, key


_client = None


def _get_client():
    """Client boto3 dùng chung — tạo 1 lần, cache lại (boto3 client thread-safe để đọc/ghi)."""
    global _client
    if _client is None:
        import boto3
        from botocore.config import Config

        _client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key or None,
            aws_secret_access_key=settings.s3_secret_key or None,
            region_name=settings.s3_region,
            # MinIO cần path-style ("http://host/bucket/key"), virtual-hosted-style
            # ("http://bucket.host/key") mặc định của boto3 không hoạt động với MinIO tự host.
            config=Config(s3={"addressing_style": "path"}),
        )
    return _client


def ensure_bucket() -> None:
    """Tạo bucket nếu chưa có — gọi 1 lần lúc app khởi động (xem main.py lifespan)."""
    client = _get_client()
    from botocore.exceptions import ClientError

    try:
        client.head_bucket(Bucket=settings.s3_bucket)
    except ClientError:
        client.create_bucket(Bucket=settings.s3_bucket)


def put_bytes(key: str, data: bytes, content_type: str | None = None) -> None:
    client = _get_client()
    extra = {"ContentType": content_type} if content_type else {}
    client.put_object(Bucket=settings.s3_bucket, Key=key, Body=data, **extra)


def get_bytes(key: str, *, bucket: str | None = None) -> bytes:
    client = _get_client()
    obj = client.get_object(Bucket=bucket or settings.s3_bucket, Key=key)
    return obj["Body"].read()


def get_bytes_from_uri(uri: str) -> bytes:
    bucket, key = parse_s3_uri(uri)
    return get_bytes(key, bucket=bucket)


def delete_key(key: str, *, bucket: str | None = None) -> None:
    client = _get_client()
    client.delete_object(Bucket=bucket or settings.s3_bucket, Key=key)


def delete_uri(uri: str) -> None:
    bucket, key = parse_s3_uri(uri)
    delete_key(key, bucket=bucket)


def delete_prefix(prefix: str) -> None:
    """Xoá mọi object có key bắt đầu bằng prefix — dùng khi purge cả thư mục applicant."""
    client = _get_client()
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=settings.s3_bucket, Prefix=prefix):
        objects = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if objects:
            client.delete_objects(Bucket=settings.s3_bucket, Delete={"Objects": objects})


def download_to_temp(uri: str) -> Path:
    """Tải object S3 về 1 file tạm trên đĩa, trả về Path — dùng khi thư viện xử lý (Pillow,
    PyMuPDF, openpyxl...) cần đường dẫn đĩa thật, không nhận được bytes/stream. Caller chịu
    trách nhiệm unlink() file tạm sau khi dùng xong."""
    bucket, key = parse_s3_uri(uri)
    suffix = Path(key).suffix
    data = get_bytes(key, bucket=bucket)
    fd, tmp_name = tempfile.mkstemp(suffix=suffix)
    tmp_path = Path(tmp_name)
    with open(fd, "wb") as f:
        f.write(data)
    return tmp_path


def upload_file(local_path: Path, key: str, content_type: str | None = None) -> str:
    """Upload 1 file cục bộ lên S3, trả về "s3://..." URI. Dùng cho export (python-docx chỉ
    ghi ra path thật, nên vẫn ghi tạm ra đĩa rồi upload thay vì đổi hẳn code sinh docx)."""
    put_bytes(key, local_path.read_bytes(), content_type)
    return make_s3_uri(key)
