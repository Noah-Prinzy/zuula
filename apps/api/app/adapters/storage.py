"""S3-compatible object storage: media submissions and accreditation documents.

`S3ObjectStorage` uses `boto3` with an optional custom endpoint, so AWS S3, Supabase Storage
(production: its S3 endpoint, path-style), Cloudflare R2 and MinIO all work. The bucket is
private: objects are addressed by key, and `put`
returns an `s3://bucket/key` reference rather than a public URL. boto3 is synchronous, so
each call runs in a thread. Without S3 credentials the stub keeps objects in this process's
memory, which is enough for the tests and for local dev.
"""

import asyncio
import logging
from typing import Protocol

from app.adapters.readiness import configured
from app.core.config import get_adapters_settings

logger = logging.getLogger("zuula.adapters.storage")


class ObjectStorage(Protocol):
    async def put(self, *, key: str, data: bytes, content_type: str) -> str:
        """Store `data` under `key`; returns a reference to the stored object."""
        ...

    async def get(self, *, key: str) -> bytes: ...

    async def delete(self, *, key: str) -> None: ...


class StubObjectStorage:
    # Shared by every stub instance in this process (the tests run the pipeline in-process).
    OBJECTS: dict[str, tuple[bytes, str]] = {}

    async def put(self, *, key: str, data: bytes, content_type: str) -> str:
        self.OBJECTS[key] = (data, content_type)
        return f"stub://zuula-media/{key}"

    async def get(self, *, key: str) -> bytes:
        if key not in self.OBJECTS:
            # In Docker Compose the worker is another process, so it can't see what the API
            # stored here. Scan an empty file rather than fail: this is the dev stub.
            logger.warning("Stub storage: %s isn't in this process; returning no bytes", key)
            return b""
        return self.OBJECTS[key][0]

    async def delete(self, *, key: str) -> None:
        self.OBJECTS.pop(key, None)


class S3ObjectStorage:
    def __init__(self, *, client, bucket: str):
        self._client = client
        self._bucket = bucket

    @classmethod
    def from_settings(cls) -> "S3ObjectStorage":
        import boto3  # only when S3 is configured: importing boto3 takes a while
        from botocore.config import Config

        settings = get_adapters_settings()
        client = boto3.client(
            "s3",
            # Supabase serves buckets as paths (…/storage/v1/s3/<bucket>), not subdomains.
            config=Config(s3={"addressing_style": "path"}) if settings.s3_endpoint_url else None,
            endpoint_url=settings.s3_endpoint_url or None,
            region_name=settings.s3_region or None,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
        )
        return cls(client=client, bucket=settings.s3_bucket)

    async def put(self, *, key: str, data: bytes, content_type: str) -> str:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return f"s3://{self._bucket}/{key}"

    async def get(self, *, key: str) -> bytes:
        def read() -> bytes:
            return self._client.get_object(Bucket=self._bucket, Key=key)["Body"].read()

        return await asyncio.to_thread(read)

    async def delete(self, *, key: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)

    async def check(self) -> None:
        """Raises unless the keys are accepted and the bucket exists (for /readyz)."""
        await asyncio.to_thread(self._client.head_bucket, Bucket=self._bucket)


_s3: S3ObjectStorage | None = None


def get_object_storage() -> ObjectStorage:
    global _s3
    if configured("s3"):
        # One client per process: boto3 clients are thread-safe and slow to build.
        if _s3 is None:
            _s3 = S3ObjectStorage.from_settings()
        return _s3
    return StubObjectStorage()
