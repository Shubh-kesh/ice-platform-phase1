# PII — strategies and custom detectors

**LEARNING ONLY** — no network, no DB. DUMMY values only.

## Hypothesis

PIIMiddleware supports redact / mask / block / hash. ICE needs email + phone on
input in product; Indian Aadhaar/PAN are a learning exercise via custom regex
detectors.

## Setup

`pii_demo.py` applies each strategy to a dummy sample containing email, phone
(+91), PAN (ABCDE1234F), and Aadhaar (2345 6789 0123).

## Observations

- redact/block hide the value entirely; mask keeps a hint; hash gives a
  deterministic digest.
- Project codes and UUIDs are never treated as PII.

## Conclusion

ICE PRODUCT: email + phone, `redact`, input only (identifiers like
`PRJ-2026-0001` are needed for tool execution and stay intact). Aadhaar/PAN:
LEARNING experiment (custom detectors exist; enabled via `ICE_AI_PII_CUSTOM_ENABLED`).
