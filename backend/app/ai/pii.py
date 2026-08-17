"""
ICE Copilot PII helpers (W7.3).

Custom regex detectors for Indian identifiers (Aadhaar, PAN) and phone numbers
(`phone` is NOT a built-in LangChain PII type). These power PIIMiddleware
custom detectors and a logging-safe `mask_pii_text` so ICE_AI_DEBUG never
writes raw PII. Never classify project codes (`PRJ-…`, `PO-…`) or UUIDs as PII.

Tests/labs use DUMMY values only — never real user data.
"""
from __future__ import annotations

import re
from typing import Any

# Indian phone: optional +91 / 0 prefix then 10 digits starting 6-9.
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)(?:\+91[\s-]?|0)?[6-9]\d{9}(?!\d)")
# Aadhaar: 4-4-4 grouping (12 digits).
AADHAAR_RE = re.compile(r"\b[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}\b")
# PAN: 5 letters + 4 digits + 1 letter.
PAN_RE = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")

# Dummy fixtures for tests/labs only.
DUMMY = {
    "phone": "+91 98765 43210",
    "aadhaar": "2345 6789 0123",
    "pan": "ABCDE1234F",
    "email": "demo@example.com",
}


def detect_phone(content: str) -> list[dict[str, Any]]:
    return [
        {"text": m.group(0), "start": m.start(), "end": m.end()}
        for m in PHONE_RE.finditer(content)
    ]


def detect_aadhaar(content: str) -> list[dict[str, Any]]:
    return [
        {"text": m.group(0), "start": m.start(), "end": m.end()}
        for m in AADHAAR_RE.finditer(content)
    ]


def detect_pan(content: str) -> list[dict[str, Any]]:
    return [
        {"text": m.group(0), "start": m.start(), "end": m.end()}
        for m in PAN_RE.finditer(content)
    ]


def mask_pii_text(text: str) -> str:
    """Replace known PII patterns with a safe placeholder (for logs).

    Cheap, deterministic, and never removes project codes/UUIDs.
    """
    masked = EMAIL_RE.sub("[EMAIL]", text)
    masked = PHONE_RE.sub("[PHONE]", masked)
    masked = AADHAAR_RE.sub("[AADHAAR]", masked)
    return PAN_RE.sub("[PAN]", masked)
