"""LEARNING ONLY — never imported by app/, no network, no DB.

PII strategies (redact / mask / block / hash) on DUMMY Indian identifiers,
using the same custom regex detectors ICE ships (phone, Aadhaar, PAN) plus the
built-in email detector. Never put real PII in labs.

Run:  python3 pii_demo.py
"""
from __future__ import annotations

import re
from langchain.agents.middleware import PIIMiddleware
from langchain_core.messages import HumanMessage

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)(?:\+91[\s-]?|0)?[6-9]\d{9}(?!\d)")
AADHAAR_RE = re.compile(r"\b[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}\b")
PAN_RE = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")

SAMPLE = "call +91 9876543210, pan ABCDE1234F, aadhaar 2345 6789 0123, email demo@example.com"


def detect(regex):
    def _detect(content: str) -> list[dict]:
        return [{"text": m.group(0), "start": m.start(), "end": m.end()} for m in regex.finditer(content)]
    return _detect


def _apply_all(strategy: str) -> str:
    from langchain.agents.middleware._redaction import PIIDetectionError

    mws = [
        PIIMiddleware("email", strategy=strategy, apply_to_input=True),
        PIIMiddleware("phone", strategy=strategy, detector=detect(PHONE_RE), apply_to_input=True),
        PIIMiddleware("aadhaar", strategy=strategy, detector=detect(AADHAAR_RE), apply_to_input=True),
        PIIMiddleware("pan", strategy=strategy, detector=detect(PAN_RE), apply_to_input=True),
    ]
    content = SAMPLE
    try:
        for mw in mws:
            result = mw.before_model({"messages": [HumanMessage(content=content)]}, None)
            if result:
                content = result["messages"][0].content
    except PIIDetectionError:
        return "[BLOCKED]"
    return content


def main() -> None:
    print("=" * 74)
    print("DUMMY PII: ", SAMPLE)
    print("=" * 74)
    for strategy in ("redact", "mask", "block", "hash"):
        print(f"[{strategy:6s}] -> {_apply_all(strategy)}")

    print()
    print("KEY: block/redact hide the value, mask keeps a hint (e.g. last 4),")
    print("hash replaces with a deterministic digest. Project codes (PRJ-2026-0001)")
    print("and UUIDs are NOT PII and are never touched.")


if __name__ == "__main__":
    main()
