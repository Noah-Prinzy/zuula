"""Short-lived download links for accreditation documents (FR-AUTH-02).

The bucket is private, so an admin reviewing an application gets signed links to this API
instead: `GET /admin/verifications/{id}/documents/{index}?expires=…&sig=…`. The signature (an
HMAC keyed by ZUULA_SECRET_KEY over the application, document and expiry) is the credential,
so a link opens in a new tab or an <img> without a session, and stops working after
`LINK_TTL`. Every download is virus-scanned first (app/adapters/clamav.py), failing closed.
"""

import hashlib
import hmac
import time
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings

LINK_TTL = timedelta(minutes=10)


def _signature(application_id: str, index: int, expires: int) -> str:
    key = get_settings().secret_key.encode()
    message = f"accreditation-document:{application_id}:{index}:{expires}".encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def signed_path(
    application_id: str, index: int, now: datetime | None = None
) -> tuple[str, datetime]:
    expires_at = (now or datetime.now(UTC)) + LINK_TTL
    expires = int(expires_at.timestamp())
    sig = _signature(application_id, index, expires)
    path = (
        f"/api/v1/admin/verifications/{application_id}/documents/{index}"
        f"?expires={expires}&sig={sig}"
    )
    return path, datetime.fromtimestamp(expires, UTC)


def link_valid(application_id: str, index: int, expires: int, sig: str) -> bool:
    if expires < time.time():
        return False
    return hmac.compare_digest(_signature(application_id, index, expires), sig)


# The upload only accepts these (account.py's _DOCUMENT_TYPES); storage keeps bytes, not types.
_MAGIC = (
    (b"%PDF", "application/pdf", "pdf"),
    (b"\x89PNG", "image/png", "png"),
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
)


def sniff(data: bytes) -> tuple[str, str]:
    """(content type, file extension) from the document's first bytes."""
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    for magic, content_type, ext in _MAGIC:
        if data.startswith(magic):
            return content_type, ext
    return "application/octet-stream", "bin"
