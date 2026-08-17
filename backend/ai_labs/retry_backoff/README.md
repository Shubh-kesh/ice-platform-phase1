# Retry backoff — ToolRetryMiddleware timing

**LEARNING ONLY** — never imported by `app/`, no network, no DB.

## Hypothesis

The pinned `ToolRetryMiddleware` waits `initial_delay * (backoff_factor **
retry_number)` seconds between attempts (`retry_number` starts at 0 for the
first retry). `backoff_factor=0` gives a constant delay.

## Setup

`retry_backoff_demo.py` runs a deterministic flaky tool that fails 3× then
succeeds (max_retries=3 → 4 attempts), with `initial_delay=0.1`, `jitter=False`,
measuring the real elapsed waits for `backoff_factor=2` vs `0`.

## Metrics

- factor=2 → waits ≈ 0.1, 0.2, 0.4 s.
- factor=0 → waits ≈ 0.1, 0.1, 0.1 s.

## Observations

Retry timing is real (measured, not configured). In ICE, these retries apply
ONLY to `web_search` (transient external failures); deterministic ICE DB errors
and RBAC denials are never retried.

## Conclusion

Exponential backoff spreads retries over time to avoid hammering an external
service; constant delay is simpler but not gentler. Use backoff for external
tools, never for deterministic errors.
