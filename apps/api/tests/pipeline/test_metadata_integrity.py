"""ExifMetadataTamperingDetector against real (tiny, in-memory) JPEGs built with Pillow — no
network, no fixture files. Covers the EXIF heuristics and the stub/switch."""

import hashlib
import io
from datetime import datetime, timedelta

import pytest
from PIL import Image

from app.core import config
from app.providers.metadata_integrity import (
    ExifMetadataTamperingDetector,
    StubMetadataTamperingDetector,
    get_metadata_tampering_detector,
)

_SOFTWARE_TAG = 0x0131
_MODIFY_DATETIME_TAG = 0x0132
_EXIF_IFD_POINTER_TAG = 0x8769
_DATETIME_ORIGINAL_TAG = 0x9003
_FMT = "%Y:%m:%d %H:%M:%S"


def _jpeg_bytes(*, software: str | None = None, modify: datetime | None = None,
                 original: datetime | None = None, with_exif: bool = True) -> bytes:
    image = Image.new("RGB", (4, 4), color="red")
    buf = io.BytesIO()
    if not with_exif:
        image.save(buf, format="JPEG")
        return buf.getvalue()
    exif = Image.Exif()
    if software is not None:
        exif[_SOFTWARE_TAG] = software
    if modify is not None:
        exif[_MODIFY_DATETIME_TAG] = modify.strftime(_FMT)
    if original is not None:
        exif.get_ifd(_EXIF_IFD_POINTER_TAG)[_DATETIME_ORIGINAL_TAG] = original.strftime(_FMT)
    image.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


def test_stub_returns_none():
    assert StubMetadataTamperingDetector().detect(b"anything") is None


def test_empty_bytes_returns_none():
    assert ExifMetadataTamperingDetector().detect(b"") is None


def test_undecodable_bytes_return_none():
    assert ExifMetadataTamperingDetector().detect(b"not an image") is None


def test_no_exif_gives_a_low_but_nonzero_score():
    data = _jpeg_bytes(with_exif=False)
    signal = ExifMetadataTamperingDetector().detect(data)
    assert signal is not None
    assert 0 < signal.score <= 0.2
    assert "No EXIF metadata" in signal.description


def test_clean_exif_with_matching_dates_scores_zero():
    now = datetime(2026, 1, 1, 12, 0, 0)
    data = _jpeg_bytes(modify=now, original=now)
    signal = ExifMetadataTamperingDetector().detect(data)
    assert signal.score == 0.0
    assert signal.description == "No EXIF anomalies found."


def test_editing_software_raises_the_score():
    data = _jpeg_bytes(software="Adobe Photoshop 25.0")
    signal = ExifMetadataTamperingDetector().detect(data)
    assert signal.score >= 0.5
    assert "Photoshop" in signal.description or "photoshop" in signal.description


def test_a_large_modify_capture_gap_raises_the_score():
    captured = datetime(2026, 1, 1, 8, 0, 0)
    modified = captured + timedelta(days=3)
    data = _jpeg_bytes(modify=modified, original=captured)
    signal = ExifMetadataTamperingDetector().detect(data)
    assert signal.score >= 0.35
    assert "resaved well after" in signal.description


def test_a_small_modify_capture_gap_does_not_flag():
    captured = datetime(2026, 1, 1, 8, 0, 0)
    modified = captured + timedelta(minutes=2)
    data = _jpeg_bytes(modify=modified, original=captured)
    signal = ExifMetadataTamperingDetector().detect(data)
    assert signal.score == 0.0


def test_the_content_hash_is_recorded_in_method():
    data = _jpeg_bytes(with_exif=False)
    signal = ExifMetadataTamperingDetector().detect(data)
    digest = hashlib.sha256(data).hexdigest()
    assert signal.method == f"exif+sha256:{digest[:16]}"


def test_multiple_findings_add_up():
    captured = datetime(2026, 1, 1, 8, 0, 0)
    modified = captured + timedelta(days=30)
    data = _jpeg_bytes(software="GIMP 2.10", modify=modified, original=captured)
    signal = ExifMetadataTamperingDetector().detect(data)
    # Editing-software marker (0.5) + a large modify/capture gap (0.35).
    assert signal.score == pytest.approx(0.85)
    assert signal.score <= 1.0


# ---- get_metadata_tampering_detector() switch ----


def test_defaults_to_stub():
    assert isinstance(get_metadata_tampering_detector(), StubMetadataTamperingDetector)


def test_exif_provider_is_used_when_configured(monkeypatch):
    monkeypatch.setenv("METADATA_TAMPERING_PROVIDER", "exif")
    config.get_analysis_settings.cache_clear()
    try:
        assert isinstance(get_metadata_tampering_detector(), ExifMetadataTamperingDetector)
    finally:
        monkeypatch.delenv("METADATA_TAMPERING_PROVIDER", raising=False)
        config.get_analysis_settings.cache_clear()


def test_unknown_provider_raises(monkeypatch):
    monkeypatch.setenv("METADATA_TAMPERING_PROVIDER", "made-up")
    config.get_analysis_settings.cache_clear()
    try:
        with pytest.raises(NotImplementedError):
            get_metadata_tampering_detector()
    finally:
        monkeypatch.delenv("METADATA_TAMPERING_PROVIDER", raising=False)
        config.get_analysis_settings.cache_clear()
