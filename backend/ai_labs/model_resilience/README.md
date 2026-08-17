# Model resilience — retry vs fallback

**LEARNING ONLY** — no network, no DB.

## Hypothesis

Model retry keeps the SAME provider/model across a transient failure; model
fallback switches to a DIFFERENT provider/model when the primary is unavailable.

## Setup

`model_resilience_demo.py` runs a primary that fails once (retry should win)
and one that always fails (fallback must win), under none / retry / fallback /
retry+fallback.

## Observations

- None: the transient error propagates.
- Retry: re-invokes the SAME provider (2 attempts) → `primary-ok`.
- Fallback (primary always down): `backup-ok`.
- Retry+fallback: retry first, then fail over if still down.

## Conclusion

Retry = transient same-provider blip; fallback = fail over when the provider is
genuinely unavailable. ICE: retry same provider first (transient), then fail
over to the configured secondary (server-side) — never user-selectable.
