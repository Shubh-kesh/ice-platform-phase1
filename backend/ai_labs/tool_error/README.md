# Tool error — safe_tool vs ToolErrorMiddleware

**LEARNING ONLY** — no network, no DB.

## Hypothesis

ICE tools already convert every exception to safe dicts via `safe_tool`.
ToolErrorMiddleware converts raw exceptions to safe messages centrally. Which
should ICE use?

## Setup

`tool_error_demo.py` shows: a deterministic domain denial (safe_tool path) and
raw-raising tools handled by `ToolErrorMiddleware`.

## Observations

- safe_tool: deterministic dicts (`not_permitted` etc.) and unexpected
  exceptions both become safe model-visible text.
- ToolErrorMiddleware: also produces safe messages for raw-raising tools.

## Conclusion (evidence)

ICE keeps **safe_tool** (hybrid): deterministic domain/RBAC errors stay typed
and safe, unexpected exceptions are caught centrally by safe_tool's `except
Exception` → safe `internal` dict. A generic ToolErrorMiddleware is redundant
for ICE tools and risks mangling typed RBAC denials if misordered, so it stays
LEARNING ONLY. Web_search uses ToolRetryMiddleware (external transient) which is
a separate, scoped mechanism.
