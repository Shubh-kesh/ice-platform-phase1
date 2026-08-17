# W7.3 — Middleware & Resilience: Checkpoint Review

**Status:** COMPLETE. Checkpoint-specific record (final Weekend-07 review after
W7.4).
**Date:** Aug 15, 2026.
**Baseline before W7.3:** W7.2 complete (417 backend / 83 AI tests), web search
+ `ToolRetryMiddleware`, AI-1 execution logging.

---

## 1. Scope

Add the full middleware/resilience stack from the Weekend-07 course: model and
tool call limits, model retry, model fallback, PII, tool-error handling,
TodoList, and a tool-selector cost benchmark — plus the read-only tool catalog
expansion to 15 tools. W7.4 NOT implemented.

## 2. Architecture

- `app/ai/middleware.py` — `build_middleware()` factory producing the fixed
  ordered list: PII (input) → memory → ModelCallLimit → ModelRetry →
  ModelFallback → ToolSelector → ToolCallLimit (global + web per-tool) →
  ToolRetry (web). `model_retry_on` predicate and local `ModelTransientError`
  live here.
- `app/ai/pii.py` — custom regex detectors (email, phone, Aadhaar, PAN) +
  `mask_pii_text` used by the logging layer; built-ins for the middleware.
- `app/ai/agent.py` — `build_agent` consumes the factory; `_build_provider_model`
  helper; `TOOL_LABELS` for all 15 tools.
- `app/ai/security.py` — `ROLE_ALLOWED_TOOLS` extended to 15 (admin/procurement
  all; supervisor 9; client 7).
- `app/ai/tools/` — new read-only tools in `field.py` (get_project_tasks,
  get_daily_site_logs), `billing.py` (get_billing_milestones, get_invoices),
  `finance.py` (get_job_costs), `inventory.py` (get_project_inventory_movements),
  `procurement.py` (get_purchase_order_deliveries).
- `app/core/config.py` — W7.3 settings (limits, retry, fallback, PII, Todo,
  selector) behind `ICE_AI_*` env flags.

## 3. Dependency/provider decision

**Pinned langchain 1.3.15 / langgraph 1.2.11-family** — reuse the pinned
versions from W7.1/W7.2 (no new SDKs). All middleware APIs were verified
against these pinned versions; no additional network/SDK exposure.

## 4. Middleware behavior verified (tests + labs)

| Middleware | Behavior verified |
|---|---|
| `ModelCallLimitMiddleware` | clean end after `run_limit` model calls |
| `ToolCallLimitMiddleware` | enforces only with `thread_limit` + `exit_behavior="end"` + checkpointer (pinned-version gotcha); run-limit always counts |
| `ModelRetryMiddleware` | retryable predicate (timeout/ratelimit/5xx); 3-call fail-fail-success; non-retryable → 1 call; exhaustion → safe error |
| `ModelFallbackMiddleware` | primary down → backup; primary ok → primary |
| `PIIMiddleware` | redact/mask/block/hash on email, phone, Aadhaar, PAN (built-ins + custom detectors) |
| `ToolErrorMiddleware` | converts raw exceptions to safe messages (LEARNING only — ICE keeps `safe_tool`) |
| `TodoListMiddleware` | adds `write_todos` planning tool (OPTIONAL) |
| `LLMToolSelectorMiddleware` | narrows schemas (proxy saves main-model tokens; OFF by default) |

## 5. Labs (`backend/ai_labs/`)

- `middleware_order/` — order matters: (A) limits-first ends early vs (B)
  retry-then-fallback ends with success; both leak-free.
- `model_resilience/` — retry same provider vs fallback to backup.
- `pii/` — all four strategies across email/phone/Aadhaar/PAN; block raises.
- `tool_error/` — safe_tool (typed dicts) vs ToolErrorMiddleware (safe message).
- `todo_middleware/` — write_todos availability + coverage rubric.
- `tool_selector_benchmark/` — token proxy: baseline ~1735 vs selector
  ~308 main-model + ~430 selector-model.
All self-contained (never imported by app/), ruff-clean, run OK.

## 6. Config defaults

Limits on (model 8, tool 15, web tool 3); model retry max 1 with backoff;
fallback provider/model server-side; PII email+phone redact input ON; custom
Aadhaar/PAN OFF; Todo OFF; selector OFF.

## 7. Test results

- AI suite: **96 passed** (83 prior + 13 `tests/test_middleware.py`).
- Labs: all 6 run clean (deterministic).
- Gates: ruff 2=2, mypy 10=10 (config.py re-baselined to line 165 after the
  W7.3 config block), oxlint 1=1, frontend build green, `git diff --check` clean.

## 8. Risks / debt

- Live provider smokes skipped: OpenRouter free tier hit its daily 429 limit;
  no Tavily key configured. Deterministic tests/labs cover behavior; a live
  smoke remains recommended after key/config is available.
- ToolCallLimit thread-level enforcement depends on memory being on; memory-less
  runs rely on run-limit counting.
- Selector savings are a token proxy; needs a live benchmark before enabling.
- Push of the W7.1/AI-1 commits is still pending (earlier attempts hung).

## 9. Verdict for W7.4

**SAFE FOR W7.4.** W7.3 scope complete and verified: ordered middleware stack
with all configurations, 15 read-only RBAC-gated tools, PII for inputs and
logs, and a measurement-gated selector. No HITL, no mutations, no live-smoke
blockers that would prevent proceeding. Proceed to W7.4 ("make me a report"
report builder + program completion review).
