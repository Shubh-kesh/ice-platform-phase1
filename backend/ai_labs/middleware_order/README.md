# Middleware order — does order matter?

**LEARNING ONLY** — no network, no DB.

## Hypothesis

The first middleware in the `create_agent(middleware=[...])` list sees the event
first. Order therefore determines PII timing, which middleware observes a model
failure, and whether retry happens before fallback.

## Setup

`middleware_order_demo.py` runs the same failing model under:
- A: PII → Limit → Retry → Fallback (ICE production order)
- B: Limit → PII → Fallback → Retry

## Observations

- A applies PII before the model call and retries the SAME provider before
  failing over; B would fail over before retrying.
- The model input shows whether the email was already redacted when the model
  saw it.

## Conclusion

ICE uses ORDER A (PII first, retry before fallback) — justified by this
experiment + the installed implementations.
