# W7.2 — Web Search & External Tool Intelligence: Checkpoint Review

**Status:** COMPLETE. Checkpoint-specific record (final Weekend-07 review after
W7.4).
**Date:** Aug 15, 2026.
**Baseline before W7.2:** W7.1 complete (401 backend / 67 AI tests), memory +
threads, AI-1 execution logging.

---

## 1. Scope

Add external web intelligence: a narrow `web_search` tool, internal+external
multi-tool reasoning, source-aware synthesis, `ToolRetryMiddleware` with
exponential backoff scoped to external transient failures, and the sequential-
vs-parallel experiment. W7.3/W7.4 NOT implemented.

## 2. Search architecture

- Provider isolated in `app/ai/web_search.py`: a minimal async `TavilyWebClient`
  (direct httpx wrapper) with a `set_client` test seam.
- Tool in `app/ai/tools/web.py` (`web_search(query, max_results)`), registered
  in the tool catalog.
- `ToolRetryMiddleware` wired in `build_agent` when search is enabled.

## 3. Dependency/provider decision

**Option B — direct async httpx wrapper around the Tavily API** (no SDK
dependency). Rationale: avoids the pydantic/httpx version-conflict risk seen
with SDK pulls (cf. langchain-openrouter), keeps provider code isolated and
injectable for deterministic fake tests, async, and matches the course's Tavily
provider without the SDK. Documented in `docs/AI_W7_2_IMPLEMENTATION_REVIEW.md`;
the key is a gitignored setting.

## 4. Configuration

`ICE_AI_WEB_SEARCH_ENABLED` (default **false**), `ICE_AI_TAVILY_API_KEY`,
`ICE_AI_WEB_SEARCH_MAX_RESULTS` (5), `ICE_AI_WEB_SEARCH_TIMEOUT_SECONDS` (10),
`ICE_AI_WEB_SEARCH_MAX_RESULT_CHARS` (2000), `ICE_AI_WEB_SEARCH_RETRIES` (2),
`ICE_AI_WEB_SEARCH_RETRY_INITIAL_DELAY` (0.2), `ICE_AI_WEB_SEARCH_RETRY_BACKOFF`
(2.0). Key/provider never exposed to the model or browser; capabilities report
only `web_search_enabled`.

## 5. Tool schema

`web_search(query: str, max_results: int = 5)` → `{status, results:[{title,
url, snippet}], total_count, returned_count, truncated}`. `max_results` is
server-bounded (`min(max_results, ICE_AI_WEB_SEARCH_MAX_RESULTS)`). No arbitrary
HTTP method/headers/URL fetch/shell; snippets truncated; no whole webpages.

## 6. Trust model

Search output is UNTRUSTED external evidence. The system prompt states it and
the tool description warns it; a test proves injected "ignore instructions"
text is returned as data (never treated as authority). No prompt-injection
middleware yet (outside W7.2).

## 7. Source-aware synthesis

Answers distinguish internal ICE facts from external web info and cite sources
(the model renders source URLs; the frontend renders them as safe links with
`rel="noopener noreferrer"`, http(s)-only, no raw HTML).

## 8. Retry middleware implementation

`ToolRetryMiddleware(max_retries=ICE_AI_WEB_SEARCH_RETRIES, tools=["web_search"],
retry_on=(WebSearchTransientError,), on_failure=on_retry_failure,
initial_delay=…, backoff_factor=…, jitter=True, max_delay=5.0)` added when
search is enabled. Scoped by tool name AND exception type → deterministic ICE
DB tools are structurally never retried.

## 9. Retry exception taxonomy

- `WebSearchTransientError` — timeout/connection/5xx/429 → retried.
- `WebSearchRejectedError` (ValueError) — malformed response/4xx → not retried;
  surfaced as a safe error dict.
- ICE RBAC/domain errors (`not_permitted`, `not_found`, validation) — never
  retried (not in scope, not in `retry_on`).

## 10. Backoff

Pinned formula `initial_delay * (backoff_factor ** retry_number)`, retry_number
starting at 0. Lab verified: factor 2 → 0.10/0.20/0.40s; factor 0 → constant
~0.10s. Jitter on in production.

## 11. safe_tool / retry interaction

`web_search` deliberately does NOT use `safe_tool`'s broad exception handling
for transient errors: it lets `WebSearchTransientError` propagate so the
middleware can observe and retry it. `on_retry_failure` returns a JSON error
dict so, after exhaustion, the model sees a safe
"external service temporarily unavailable" message AND the SSE adapter
classifies it correctly (ok=False, error=external_service_error). Deterministic
ICE tools keep `safe_tool`.

## 12. Memory interaction

Tested: turn 1 "We're discussing cement for Green Heights." → turn 2 "How much
do we have?" → turn 3 "Search the current market price." — conversation context
is carried by W7.1 memory and turn 3 uses `web_search` appropriately.

## 13. Logging/metrics

Tool started/completed logs add `external=true` for `web_search`, plus
`search_result_count` and `result_chars`. Retry attempt counts are NOT surfaced
per-attempt in the stream (the middleware retries internally before the final
ToolMessage); the exhausted-failure error kind is observable, and the
`retry_backoff` lab measures timing deterministically. No key/raw response
logged.

## 14. Tests

`tests/test_web_search.py` (16 tests): success shape, bounds/truncation,
disabled/missing-key, malformed provider, trust-model prompt + description,
injection-text-is-data, retry success-first, fail-then-success (3 calls),
exhaustion safe error, non-retryable immediate (1 call), ICE-tool-never-retried,
scenario inventory+web, scenario web-only-when-justified, scenario web-only-
trends, memory+web multi-turn. Deterministic (injected fake client, no network).

## 15. Labs

- `backend/ai_labs/web_multi_tool/` — parallel (0.31s / 2 calls) vs sequential
  (0.51s / 3 calls) with mock latency.
- `backend/ai_labs/retry_backoff/` — factor 2 (0.10/0.20/0.40) vs factor 0
  (constant ~0.10) measured real waits.

## 16. Memory interaction

See §12 (memory untouched; external tool works inside threads).

## 17. Frontend

"Web search" badge when `web_search_enabled`; tool pill shows "Searching the
web…" for the web label; assistant answers render http(s) URLs as safe links
(`rel="noopener noreferrer"`, `target="_blank"`, no raw HTML). Build + oxlint
PASS.

## 18. Live smoke

**Skipped** — no `ICE_AI_TAVILY_API_KEY` configured in the environment. No
provider quota spent. Deterministic tests/labs cover the behavior.

## 19. Limitations / risks

- Web search default OFF (needs a key).
- Retry attempt counts are not streamed per-attempt (only the final outcome).
- Tavily is a paid/variable external service (cost/rate bounded by
  `ToolCallLimitMiddleware` in W7.3 — deliberately NOT introduced here).
- `on_retry_failure` returns a JSON error dict; the exhausted message leaks the
  exception class name in the middleware's own formatting only on the
  non-JSON path (our path is JSON, so the model sees our safe detail).

## 20. Deviations from plan

- Provider = httpx wrapper (Option B) instead of the Tavily SDK (documented
  decision; no dependency risk, deterministic fakes).
- `ToolCallLimitMiddleware` NOT introduced (deferred to its W7.3 experiment).
- Per-attempt retry logging not added (middleware-internal; observed via labs).

## 21. Verdict

**SAFE FOR W7.3.** Web intelligence, retry/backoff (external-only), trust model,
tests (67+16 = 83 AI), labs, and docs complete; no migration; no new dependency;
defaults safe (search off). No commit/push.
