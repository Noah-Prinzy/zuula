"""MetadataTamperingDetector: an ai_signals entry for image submissions
(app/providers/analysis.py) based on EXIF metadata inconsistencies and a content hash —
§5.3's "Metadata Tampering" detection method (EXIF analysis + hash verification, >95% target
in the spec's table). Unlike every other row in that table, this one needs no training data
and no model: EXIF tags are plain file metadata, and a SHA-256 digest is just arithmetic over
the bytes — both squarely achievable without the labelled corpus or GPU budget this project
doesn't have.

It's a heuristic, not a forensic tool: a clean EXIF block doesn't prove authenticity (lots of
untouched photos have thin EXIF), and a missing one doesn't prove tampering (most phones and
social platforms strip EXIF on their own, which is exactly why this signal's score stays low
for that case alone). The SHA-256 digest is recorded on every check as part of the report's
evidentiary trail (the "hash verification" half of §5.3's method) — there is no reference-hash
registry yet for it to be looked up against, so for now it is "verification" only in the
read-and-record sense, not a known-good/known-bad lookup.

Same real-or-stub convention as app/providers/ai_text_detector.py, even though there's no
model download here: METADATA_TAMPERING_PROVIDER defaults to `stub` so a routine pipeline run
doesn't silently start flagging submissions on a heuristic nobody has reviewed against real
traffic yet. Set it to `exif` to turn the real check on.
"""

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from app.core.config import get_analysis_settings
from app.schemas.fact_check import AISignal

logger = logging.getLogger("zuula.providers.metadata_integrity")

_SOFTWARE_TAG = 0x0131  # base IFD "Software"
_MODIFY_DATETIME_TAG = 0x0132  # base IFD "DateTime" (last save)
_EXIF_IFD_POINTER_TAG = 0x8769
_DATETIME_ORIGINAL_TAG = 0x9003  # Exif sub-IFD: when the shot was actually taken

_EXIF_DATETIME_FORMAT = "%Y:%m:%d %H:%M:%S"

# Image editors whose name in the EXIF "Software" tag is itself a tampering signal — a camera
# or phone writes its own firmware/app name there, not one of these.
_EDITING_SOFTWARE_MARKERS = (
    "photoshop",
    "gimp",
    "lightroom",
    "snapseed",
    "picsart",
    "facetune",
    "affinity photo",
    "paint.net",
    "pixelmator",
    "canva",
)

# A resave within this long of the capture time is normal camera/phone behaviour (HDR merge,
# burst processing, sidecar writes); a bigger gap means the file was edited and saved well
# after it was taken.
_SUSPICIOUS_RESAVE_GAP_SECONDS = 6 * 3600


class MetadataTamperingDetector(Protocol):
    def detect(self, data: bytes) -> AISignal | None:
        """An AISignal estimating how likely an uploaded image's metadata shows signs of
        tampering, or None when there's nothing to say (empty input, or it can't be decoded
        as an image)."""
        ...


class StubMetadataTamperingDetector:
    def detect(self, data: bytes) -> AISignal | None:
        return None


@dataclass
class _Findings:
    reasons: list[str] = field(default_factory=list)
    score: float = 0.0


def _parse_exif_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), _EXIF_DATETIME_FORMAT)
    except ValueError:
        return None


def _inspect_exif(exif) -> _Findings:
    findings = _Findings()
    if not exif:
        findings.reasons.append(
            "No EXIF metadata present (common for screenshots or re-encoded images, but also "
            "for a stripped original)."
        )
        findings.score += 0.15
        return findings

    software = str(exif.get(_SOFTWARE_TAG, "")).strip().lower()
    if any(marker in software for marker in _EDITING_SOFTWARE_MARKERS):
        findings.reasons.append(f"EXIF 'Software' tag names an image editor: {software!r}.")
        findings.score += 0.5

    try:
        exif_ifd = exif.get_ifd(_EXIF_IFD_POINTER_TAG) or {}
    except Exception:  # noqa: BLE001 — a malformed sub-IFD shouldn't fail the whole check
        exif_ifd = {}

    modified = _parse_exif_datetime(exif.get(_MODIFY_DATETIME_TAG))
    captured = _parse_exif_datetime(exif_ifd.get(_DATETIME_ORIGINAL_TAG))
    if modified and captured:
        gap_seconds = abs((modified - captured).total_seconds())
        if gap_seconds > _SUSPICIOUS_RESAVE_GAP_SECONDS:
            findings.reasons.append(
                f"EXIF modify date is {gap_seconds / 3600:.1f} hours after the capture date "
                "(DateTimeOriginal) — the file was resaved well after it was taken."
            )
            findings.score += 0.35
    elif modified and not captured:
        findings.reasons.append(
            "EXIF has a modify date but no original capture date (DateTimeOriginal)."
        )
        findings.score += 0.1

    return findings


class ExifMetadataTamperingDetector:
    """Real implementation: Pillow's own EXIF reader, no model, no network. Decodes the image
    once to read its EXIF block, and takes a SHA-256 of the raw bytes for the report's audit
    trail."""

    def detect(self, data: bytes) -> AISignal | None:
        if not data:
            return None
        digest = hashlib.sha256(data).hexdigest()
        try:
            import io

            from PIL import Image

            with Image.open(io.BytesIO(data)) as image:
                exif = image.getexif()
                findings = _inspect_exif(exif)
        except Exception:  # noqa: BLE001 — not a decodable image: nothing to say
            logger.warning("Metadata tampering check couldn't decode the image", exc_info=True)
            return None

        score = min(findings.score, 1.0)
        reasons = findings.reasons or ["No EXIF anomalies found."]
        return AISignal(
            id="metadata-integrity",
            label="Metadata tampering",
            description=" ".join(reasons),
            score=round(score, 2),
            threshold=0.5,
            method=f"exif+sha256:{digest[:16]}",
        )


def get_metadata_tampering_detector() -> MetadataTamperingDetector:
    """METADATA_TAMPERING_PROVIDER: `exif` for the real check, `stub` (the default)
    otherwise."""
    settings = get_analysis_settings()
    choice = settings.metadata_tampering_provider.strip().lower()
    if choice not in ("stub", "exif"):
        raise NotImplementedError(
            f"Unknown METADATA_TAMPERING_PROVIDER '{settings.metadata_tampering_provider}': "
            "use 'exif' or 'stub'."
        )
    if choice == "stub":
        return StubMetadataTamperingDetector()
    return ExifMetadataTamperingDetector()
