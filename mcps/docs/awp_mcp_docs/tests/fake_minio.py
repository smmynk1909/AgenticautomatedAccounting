"""In-memory stand-in for `minio.Minio` — enough of its surface for
`DocStorage` (bucket_exists/make_bucket/put_object/stat_object/get_object).
No real MinIO server involved, matching the sqlite-instead-of-postgres /
fakeredis-instead-of-redis pattern used across the other mcp test suites.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

from minio.error import S3Error


@dataclass
class _StoredObject:
    data: bytes
    content_type: str
    metadata: dict[str, str]


class _FakeStatResult:
    def __init__(self, metadata: dict[str, str]) -> None:
        self.metadata = metadata


class _FakeGetResponse:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data

    def close(self) -> None:
        pass

    def release_conn(self) -> None:
        pass


@dataclass
class FakeMinio:
    _buckets: set[str] = field(default_factory=set)
    _objects: dict[tuple[str, str], _StoredObject] = field(default_factory=dict)

    def bucket_exists(self, bucket_name: str) -> bool:
        return bucket_name in self._buckets

    def make_bucket(self, bucket_name: str) -> None:
        self._buckets.add(bucket_name)

    def put_object(
        self,
        bucket_name: str,
        object_name: str,
        data: io.BytesIO,
        *,
        length: int,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        # httpx-style file-like: DocStorage always passes io.BytesIO. Real
        # MinIO/S3 echoes user metadata back from stat_object/get_object
        # prefixed with "x-amz-meta-" — DocStorage.get() reads it back under
        # that prefix, so the fake has to write it the same way or every
        # lookup silently falls through to the "not found" defaults.
        prefixed = {f"x-amz-meta-{k}": v for k, v in metadata.items()}
        self._objects[(bucket_name, object_name)] = _StoredObject(
            data=data.read(), content_type=content_type, metadata=prefixed
        )

    def stat_object(self, bucket_name: str, object_name: str) -> _FakeStatResult:
        obj = self._objects.get((bucket_name, object_name))
        if obj is None:
            raise S3Error(
                response=None,  # type: ignore[arg-type]
                code="NoSuchKey",
                message="not found",
                resource=f"/{bucket_name}/{object_name}",
                request_id="fake-request-id",
                host_id="fake-host-id",
                bucket_name=bucket_name,
                object_name=object_name,
            )
        return _FakeStatResult(obj.metadata)

    def get_object(self, bucket_name: str, object_name: str) -> _FakeGetResponse:
        obj = self._objects.get((bucket_name, object_name))
        if obj is None:
            raise S3Error(
                response=None,  # type: ignore[arg-type]
                code="NoSuchKey",
                message="not found",
                resource=f"/{bucket_name}/{object_name}",
                request_id="fake-request-id",
                host_id="fake-host-id",
                bucket_name=bucket_name,
                object_name=object_name,
            )
        return _FakeGetResponse(obj.data)
