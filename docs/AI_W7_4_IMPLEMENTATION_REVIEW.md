# W7.4 — HITL, Tool Emulation & Controlled Actions: Checkpoint Review

**Status:** COMPLETE. Checkpoint-specific record (final Weekend-07 review after
W7.4).
**Date:** Aug 15, 2026.
**Baseline before W7.4:** W7.3 complete (430 backend / 96 AI tests), middleware
stack, 15 read-only tools.

---

## 1. Scope

Controlled mutations behind HumanInTheLoop, tool emulation, resume ownership,
the remaining taught concepts (InMemoryStore, return_direct, dynamic gating,
structured report workflow), and the final Weekend-07 integration/security
review. No RAG/MCP/multi-agent/vector DB.

## 2. API findings (verified on pinned langchain 1.3.15 / langgraph 1.2.11)

- `HumanInTheLoopMiddleware(interrupt_on={name: bool|InterruptOnConfig})`.
  `True` = all four decisions; `InterruptOnConfig` = `allowed_decisions` +
  optional `description` (str or callable) + optional `when`.
- The interrupt is NOT raised as `GraphInterrupt` here — it surfaces as an
  `updates` stream node named `__interrupt__`; the checkpoint state
  (`agent.get_state(config)`) carries it as `state.interrupts[].value` = a dict
  `{action_requests:[{name,args,description}], review_configs:[{action_name,
  allowed_decisions}]}` with `state.next` paused at
  `HumanInTheLoopMiddleware.after_model`.
- Resume: `agent.invoke(Command(resume={"decisions":[...]}), config)` where a
  decision is `{"type":"approve"}` | `{"type":"edit","edited_action":{name,args}}`
  | `{"type":"reject","message"}` | `{"type":"respond","message"}`.
- Decisions must be validated server-side BEFORE resume: invalid/unknown types
  and non-resumable threads raise cleanly.
- `LLMToolEmulator(tools=[...], model=...)` replaces the real tool execution
  with `model.invoke(prompt)["content"]` — the real function never runs.
- `InMemoryStore`, `create_agent(store=...)`, `ToolRuntime.store.put/get`,
  `BaseTool.return_direct`, and `wrap_model_call` all verified.

## 3. HITL architecture

```
agent proposes mutating tool
  -> HumanInTheLoopMiddleware interrupts (requires checkpointer)
  -> SSE `approval_required` (safe card: label, summary, editable_fields,
     allowed_decisions)
  -> POST /assistant/resume {thread_id, decision, edited_action?, message?}
  -> validated against the tool's allowed decisions
  -> Command(resume={"decisions":[...]}) on the SAME user-namespaced thread
  -> tool executes ONLY on approve/edit (edit = original args merged with the
     human's edited values)
  -> ICE self-RBAC + domain validation + record_audit + commit
  -> SSE continuation (assistant_resumed / tool_* / action_completed /
     assistant_complete)
```

## 4. Resume ownership

The thread resolves to `{user_id}::{thread_id}` via the W7.1 namespaced
keyspace. Another user posting the SAME external thread id reaches their OWN
(empty) thread -> `no_pending_approval`. Identity is rebuilt from
authentication on every resume; ActorContext is never the authority inside
checkpoint state. Same-thread-id different-user isolation tested.

## 5. Mutating tools implemented

- `create_task` — reuses `project_access` (`get_project_for_update`,
  `assert_can_view_project`, `assert_project_writable`), `services.tasks`
  (`validate_task_dates`, `validate_dependency`, `apply_schedule`), `record_audit`
  + schedule-shift auditing + `notify_schedule_shift`, same transaction.
- `create_daily_site_log` — reuses `project_access`, `record_audit`; adds a
  same-day duplicate guard (the REST route uses an Idempotency-Key; the AI path
  has no header, so an identical `(project_id, log_date)` is rejected).

Both are low-risk only. NOT enabled (explored only via the emulator):
receive_purchase_order, record_job_cost, PO approval, lifecycle transitions,
inventory adjustments, user/role changes.

## 6. RBAC / audit / transactions

- Role gate mirrors REST `write_roles` = ADMIN + SITE_SUPERVISOR. Procurement
  does NOT get the mutating tools (its write surface is procurement/finance).
  Client NEVER gets them (defense in depth) and the tools hard-deny a client
  actor anyway.
- HITL is additional: approval does not grant role/project access (client
  approve -> still denied, tested).
- `record_audit` is the business history; AI logs are operational traces only.
- HTTPException from project_access/domain validation is converted to safe
  ToolError INSIDE the tool body (a re-raise inside `safe_tool`'s except-handler
  would escape — pinned-version finding).

## 7. Approve / Edit / Reject / Respond results

- approve: exactly one mutation + one audit entry.
- edit: only the edited values execute (server merges original args so
  project context survives).
- reject: zero mutation; `ToolMessage(status="error")`.
- respond: zero mutation; the human's message is the tool result. `create_task`
  allows respond; `create_daily_site_log` does NOT (append-only field record).

## 8. Double-resume / replay

LangGraph resume semantics: resuming a thread that already completed its
interrupt does not re-execute the tool (verified: executed calls stayed at one).
The site-log duplicate-day guard is a second, domain-level backstop. No broad
idempotency system was invented; residual risk = process-local interruption loss
on restart (documented).

## 9. Emulator

`ai_labs/llm_tool_emulator/` + `tests/test_w7_4_concepts.py`: the agent picks
`receive_purchase_order`, real function executions = 0, synthetic result clearly
marked simulated. The emulator validates decision paths before enabling
sensitive tools.

## 10. Emulator vs real comparison

| | Emulated create_task/PO | Real HITL create_task |
|---|---|---|
| tool selection | yes (synthetic) | yes |
| model calls / tool calls | same path | same path |
| DB mutation count | 0 | 1 |
| audit rows | 0 | 1 |

## 11. InMemoryStore

`ai_labs/inmemory_store/`: preference set in thread A, read in thread B for the
same user; a different user with the same thread id reads None. Process-local
limitation documented. Not added to production.

## 12. State / context / store

CONTEXT = ActorContext (who is calling NOW); STATE = thread-scoped messages
(checkpointer); STORE = cross-thread in-process data (InMemoryStore). Explained
in the simple summary §14 and the lab README.

## 13. return_direct

`ai_labs/return_direct/`: `return_direct=False` → 2 model calls vs `True` → 1.
LEARNING ONLY — no ICE tool uses it.

## 14. Dynamic tool gating

`ai_labs/tool_gating/` + tests: `wrap_model_call` shrinks the model-visible
toolset; hard per-tool RBAC unchanged. ICE already does static role pruning, so
this is a lab. Pinned-version note: the wrapped async function receives
`(request, handler)` and must be async for `ainvoke`.

## 15. Report workflow

`ai_labs/report_workflow/`: structured `ProjectWeeklyReport` (10 sections) built
from read-only data, validated by Pydantic. Read-only → no HITL. Kept as a lab;
a live product integration would call the real read-only tools.

## 16. Tests (new)

- `tests/test_hitl.py` (12): interrupt + DB unchanged; approve/edit/reject/
  respond; cross-user resume blocked; same-thread-id isolation; client cannot
  escalate; invalid decision; safe SSE; fresh saver loses interrupt; site-log
  append + duplicate-day guard.
- `tests/test_mutating_tools.py` (15): direct RBAC (admin/supervisor allowed;
  procurement/client denied; unassigned supervisor denied), IDOR, archived
  read-only, validation rollback, audit rows, result shape, toolset exclusion.
- `tests/test_w7_4_concepts.py` (4): emulator (0 executions), store isolation,
  return_direct call count, dynamic gating.
- AI suite total: **127 passed** (96 prior + 31 new).

## 17. Labs (new, all self-contained / ruff-clean / run OK)

`hitl_lifecycle/`, `llm_tool_emulator/`, `inmemory_store/`, `return_direct/`,
`tool_gating/`, `report_workflow/` — each with a README (hypothesis, setup,
observations, conclusion) and never imported by `app/`.

## 18. Security

- Resume resolves through the authenticated actor's namespace only.
- SSE approval card exposes only whitelisted editable fields + safe summary.
- No identity/role/system-prompt/checkpoint key in SSE or logs (tested).
- Mutation tool args are model-proposed but the human decision comes from the
  resume path; approval can never fabricate identity.

## 19. Limitations

- Interrupts are process-local (InMemorySaver) — restart loses pending
  approvals; no durable approvals table (explicitly deferred).
- Mutations default OFF; the read-only product is preserved.
- Live provider smoke skipped (OpenRouter daily quota; no Tavily key).

## 20. Deviations

- `create_task` allows `respond`; `create_daily_site_log` does not (append-only
  rationale).
- The site-log AI path uses a same-day duplicate guard instead of an HTTP
  Idempotency-Key (none exists outside the REST route).
- `_raise_as_tool_error` must run inside the tool body (pinned-version safe_tool
  finding), not inside `safe_tool`'s except-handler.

## 21. Verdict

**WEEKEND-07 COMPLETE — SAFE TO REVIEW/COMMIT.** W7.4 scope complete and
verified; all taught concepts through Weekend 07 are implemented; mutations are
HITL-guarded and reuse the ICE RBAC/audit/transaction rules; no RAG/MCP/multi-
agent/vector DB introduced; no commit/push performed.
