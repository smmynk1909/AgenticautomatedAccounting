"""MinIO object storage wrapper — doc 08 §3's `store_file`/`get_file`.

`scope` (a list of role names, or the literal `"public"`) is stored as MinIO
object metadata alongside the bytes — there's no Postgres table for
mcp-docs (doc 12 §2's tree lists none), so this is the only place that
scope survives between a `store_file` and a later `get_file` call.
"""

from __future__ import annotations

import io
import json
import uuid
from dataclasses import dataclass

from minio import Minio
from minio.error import S3Error

SCOPE_META_KEY = "X-Amz-Meta-Awp-Scope"
FILENAME_META_KEY = "X-Amz-Meta-Awp-Filename"
CONTENT_TYPE_META_KEY = "X-Amz-Meta-Awp-Content-Type"


@dataclass(frozen=True)
class StoredFile:
    data: bytes
    filename: str
    content_type: str
    scope: list[str] | str


class DocStorage:
    def __init__(self, client: Minio, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    def ensure_bucket(self) -> None:
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)

    def put(
        self, data: bytes, *, filename: str, content_type: str, scope: list[str] | str
    ) -> str:
        object_name = f"{uuid.uuid4()}/{filename}"
        self._client.put_object(
            self._bucket,
            object_name,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
            metadata={
                "awp-scope": json.dumps(scope),
                "awp-filename": filename,
                "awp-content-type": content_type,
            },
        )
        return f"minio://{self._bucket}/{object_name}"

    def get(self, uri: str) -> StoredFile:
        object_name = _object_name_from_uri(uri, self._bucket)
        try:
            stat = self._client.stat_object(self._bucket, object_name)
            resp = self._client.get_object(self._bucket, object_name)
            try:
                data = resp.read()
            finally:
                resp.close()
                resp.release_conn()
        except S3Error as exc:
            raise FileNotFoundError(f"no such file: {uri}") from exc

        meta = stat.metadata or {}
        scope_raw = meta.get("x-amz-meta-awp-scope", '"public"')
        return StoredFile(
            data=data,
            filename=meta.get("x-amz-meta-awp-filename", object_name.rsplit("/", 1)[-1]),
            content_type=meta.get("x-amz-meta-awp-content-type", "application/octet-stream"),
            scope=json.loads(scope_raw),
        )


def _object_name_from_uri(uri: str, bucket: str) -> str:
    prefix = f"minio://{bucket}/"
    if not uri.startswith(prefix):
        raise ValueError(f"not a minio:// uri for bucket {bucket!r}: {uri}")
    return uri[len(prefix) :]
