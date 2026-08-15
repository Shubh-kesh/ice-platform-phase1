# AI-1.1 — ICE Copilot foundation: a simple summary

This is a plain-language reference for me (the owner). It is NOT the technical
review. Full detail lives in `docs/AI1_IMPLEMENTATION_PLAN.md`.

## 1. What we built

The foundation of the **ICE Copilot** — a read-only AI assistant that can
answer questions about real ICE data (projects, health, budget, inventory,
purchase orders, notifications). This slice built:

- the `backend/app/ai/` package (context, security, prompts, tools, model factory),
- exactly **seven read-only tools**,
- the security plumbing that makes the assistant safe,
- a learning experiment under `backend/ai_labs/toolruntime_context/`.

No chat UI yet, no streaming endpoint yet, no memory, no web search.

## 2. Why we built it

To prove the core mechanics work safely before adding the chat surface: the
assistant must be able to fetch real data, enforce the exact same permissions
as the normal ICE app, and never let the AI model "talk its way" into data it
is not allowed to see. If the tools and security are solid, everything after
(AI-1.2 chat, AI-2 memory, …) builds on a safe base.

## 3. Main LangChain concepts used

- `create_agent` — the harness that lets a model decide which tools to call.
- `@tool` + `args_schema` — tools the model can see and call; the model sees
  only the tool's arguments (not the hidden `runtime`).
- `ToolRuntime` — the hidden per-invocation object injected into every tool. It
  carries the authenticated user (via `runtime.context`) and is invisible to
  the model.
- Model abstraction (`init_chat_model`) — provider-agnostic: we can switch from
  OpenAI to another provider by changing settings, not code.

## 4. ICE concepts reused

- `project_access.py` (assignment checks, archived-project hiding, client
  blocking) — the exact same guards the REST API uses.
- Role-scoped project serialization (M3/M6) — a client gets the same limited
  "project card" the normal API gives them.
- The service layer (`health`, `finance.budget_rollup`) and ORM models — the
  tools reuse the real queries, they don't write new ones.
- M6 client rules — clients can only see what the client portal lets them see.

## 5. The seven tools created

| Tool | What it answers | Who can use it |
|---|---|---|
| `list_projects` | Which projects do I have? | everyone (role-scoped list) |
| `get_project` | Details of one project | everyone (role-scoped shape) |
| `get_project_health` | Is a project on track? Why? | admin, procurement, supervisor |
| `get_project_budget` | Budget spent / remaining / by cost code | admin, procurement |
| `get_project_inventory` | Stock levels and low-stock flags | admin, procurement, assigned supervisor |
| `get_purchase_orders` | Open POs, vendors, totals | admin, procurement |
| `get_my_notifications` | My notification feed | everyone (own only) |

## 6. How ToolRuntime authentication works (in simple terms)

1. You log in normally — the app knows who you are (the same way it always does).
2. The backend puts your `user_id` + `role` into a **frozen** "actor" box.
3. That box is injected into the assistant run through `ToolRuntime.context`.
4. Every tool opens the box to see who is asking, and then applies the normal
   ICE permission rules before returning data.
5. The AI model can't see the box or change it — `runtime` is hidden from the
   tool's argument list. So "pretend you're an admin" can never work.

## 7. One example request flow

You ask: *"Why is Green Heights unhealthy?"*

1. The assistant decides to call `get_project_health(project_id=...)`.
2. The tool opens the actor box: `you are a site supervisor, assigned to Green
   Heights`.
3. It checks the normal rules (you may see this project; health is allowed for
   your role; the project is not archived).
4. It runs the existing health calculation and returns a compact summary
   (overall / timeline / budget verdicts + reasons).
5. The assistant answers using only that tool data.

## 8. Security rules

- Every tool checks permissions itself — even if a forbidden tool somehow
  reached the model, it says "not permitted".
- Identity never comes from the model — only from your login.
- No `execute_sql` / generic database tool exists — only these seven narrow,
  business-specific tools.
- No tool changes anything — all reads, no writes, no commits.
- Clients get exactly what the client portal already gives them — nothing more.
- Tool output is capped (4000 characters by default) so we don't dump the
  database into the model.

## 9. Tests performed

- 27 new AI tests (all pass) plus the full backend suite (**361 passed**).
- Tests use a **fake model**, so no OpenAI key or internet is needed.
- Verified: all seven tools allow/deny per role; clients are locked to the M6
  surface; cross-project snooping is blocked; identity is invisible in tool
  schemas; nothing mutates the database; the model factory works without
  network; disabled/missing-key fails cleanly.
- `ruff` and `mypy` delta gates pass (no new findings), `git diff --check` clean.

## 10. What I should learn/practice manually

- Run the learning experiment:
  `python3 backend/ai_labs/toolruntime_context/toolruntime_context_demo.py`
  and see the BAD vs GOOD tool schemas side by side.
- Read `backend/app/ai/tools/projects.py` and trace one tool end to end.
- Try changing `ICE_AI_PROVIDER`/`ICE_AI_MODEL` in your `.env` to see the model
  factory is provider-agnostic.

## 11. What is NOT built yet

- The chat endpoint (`POST /assistant/chat`) and streaming — **AI-1.2**.
- The frontend Assistant page — **AI-1.2**.
- Conversation memory / checkpointing — **AI-2**.
- Web search — **AI-3**.
- Limits / fallback / PII middleware — **AI-4**.
- Tool selector — **AI-5**. Mutations / human-in-the-loop — **AI-6**.

## 12. Next step: AI-1.2

Build the authenticated chat endpoint (streaming events) and the SPA
Assistant surface on top of this foundation, wired to the same seven tools and
the same security rules.

---

# AI-1.2 — Agent orchestration + streaming API: a simple summary

## 1. What `create_agent` does

`create_agent` is LangChain's ready-made agent harness. You give it a model,
a list of tools, and a system prompt; it builds the loop that runs each turn:
ask the model → if it wants a tool, run the tool → feed the result back → ask
again → until it gives a final answer. We don't hand-write any of that routing.

## 2. How the ICE agent loop works

For one chat message the loop is:

1. Your message becomes a `HumanMessage`.
2. The model is called with the role-filtered tool set + system prompt.
3. The model returns an `AIMessage` — either a final answer, or a *tool call*.
4. If it's a tool call, our ICE tool runs (with your identity from
   `ToolRuntime.context`), producing a `ToolMessage`.
5. The `ToolMessage` is added to the conversation and the model is called again.
6. It repeats until the model gives a final `AIMessage`.

## 3. HumanMessage vs AIMessage vs ToolMessage

- **HumanMessage** — what you said (and any earlier context).
- **AIMessage** — what the model said. If it carries `tool_calls`, the model is
  *requesting* a tool, not answering yet.
- **ToolMessage** — the tool's result, fed back to the model as new context.

## 4. How tool calling differs from a normal LLM response

A normal response is one call → one answer. With tool calling, the model's
first output is a *request to run a tool*; the actual data comes from the tool
(the database), and only then does the model write the final answer using that
data. So the answer is grounded in real ICE data, not the model's memory.

## 5. How ToolRuntime enters the flow

Every ICE tool gets a hidden `runtime` object. It carries your identity
(`user_id`, `role`), which was injected by the backend from your login — the
model can't see it or change it. The tool uses that identity to run the normal
ICE permission checks before returning anything.

## 6. How streaming works

The API returns a Server-Sent Events (SSE) stream. As the loop runs, we emit
events: `assistant_start`, `assistant_token` (each piece of the final answer),
`tool_started` / `tool_finished` (activity pills), `assistant_complete`, or
`error`. The browser shows text appearing live and little "Checking project
health…" pills while tools run.

## 7. Why ICE translates LangChain events into its own SSE events

LangChain/LangGraph's internal event names and shapes change between versions
and are implementation details. We translate them once, inside `agent.py`, into
a stable ICE event contract. The frontend depends on OUR events, so a LangChain
upgrade can't break the UI — only the adapter needs updating.

## 8. How RBAC still protects data even if the model chooses a forbidden tool

Two layers:
1. The model only ever receives the tools your role is allowed to use
   (defense in depth) — a client never even sees the budget tool.
2. Even if a forbidden tool somehow ran, the tool itself re-checks your role
   and returns `not_permitted`. Tested with a scripted "ignore instructions,
   I am admin" model: the budget tool refused, no budget data ever appeared in
   the stream, and nothing was mutated.

## 9. How usage/token metrics are collected

The provider attaches token counts to the final model chunk. We capture them
defensively (if a provider omits them, the request still works and they stay
0). Each request records model-call count, tool-call count, input/output/total
tokens, tool-result size and authorization denials. Only the safe subset is
sent to the browser in `assistant_complete` (model_calls, tool_calls,
input/output/total tokens, took_ms).

## 10. What the learning lab demonstrates

`backend/ai_labs/agent_loop/` uses a fake model that records every input it
receives. Run it to see: the messages before the first model call, the tool
schema, the full message timeline, what was sent to each model call (call #2
contains the `ToolMessage`), and the final answer with usage metadata.

## 11. Example end-to-end request

You ask *"why is this project unhealthy?"* →
`POST /api/v1/assistant/chat` (authenticated) →
`assistant_start` → the model requests `get_project_health` →
`tool_started: "Project health"` → the tool checks your identity + permissions
and returns real health data → `tool_finished` → the model writes the final
answer, streamed as `assistant_token`s → `assistant_complete` with metrics.

## 12. What is still missing until AI-1.3

- The **frontend** Assistant page (chat UI, pills, streaming display) — **AI-1.3**.
- Conversation memory / checkpointing — **AI-2**.
- Web search — **AI-3**. Limits/fallback/PII middleware — **AI-4**.
- Tool selector — **AI-5**. Mutations / human-in-the-loop — **AI-6**.

---

# AI-1.3 — Frontend + structured-output lab + smoke tests: a simple summary

## 1. What frontend was added

A real ICE Copilot chat page at `/assistant`:
- `pages/Assistant.tsx` — the page (loads capabilities, handles loading /
  disabled / unavailable states).
- `components/AssistantChat.tsx` — the chat panel (messages, streaming text,
  tool pills, composer, stop button).
- `lib/assistant.ts` — the streaming transport + SSE parser.
- `types/assistant.ts` — the shared types.
- A new "ICE Copilot" item in the sidebar navigation.

No new frontend framework or library — just the existing React/Tailwind stack.

## 2. What multi-provider support means

The Copilot's model is built from settings, not code. `ICE_AI_PROVIDER` picks
`openai`, `anthropic`, `groq`, or `openrouter`, and `ICE_AI_MODEL` picks the
model. The matching key (`ICE_AI_OPENAI_API_KEY`, …) is used, with
`ICE_AI_API_KEY` as the fallback. The UI never sees or chooses the provider.

## 3. How to switch providers safely

In `backend/.env`, set `ICE_AI_PROVIDER`, `ICE_AI_MODEL`, and the matching
`ICE_AI_{PROVIDER}_API_KEY`. Restart the backend. That's it — tools, RBAC, and
the UI don't change. Provider/base URL/keys are server-controlled; the chat
request only ever sends `{"message": "..."}`.

## 4. How browser streaming works

The page uses `fetch` + `ReadableStream` to read the server's streamed answer.
As bytes arrive they are split into events and the text is appended to the
message bubble live.

## 5. SSE in simple terms

Server-Sent Events is a plain-text format: lines starting with `event:` name
the event and `data:` carry JSON. The backend emits:
`assistant_start`, `assistant_token` (each piece of the answer), `tool_started`,
`tool_finished`, `assistant_complete`, `error`.

## 6. Why fetch/ReadableStream instead of EventSource

`EventSource` only supports GET and can't send a Bearer token header. Our chat
is an authenticated POST, so we use `fetch` and read the stream manually. The
parser also tolerates events split across chunks, several events per chunk,
and malformed/unknown frames safely.

## 7. How tool progress appears

While a tool runs you see a small pill: "Checking Project health…" with a
spinner, then a ✓ when done, or an "unavailable" style if the tool denied. The
backend sends safe display labels — never raw tool names, arguments, results,
or internal details.

## 8. UI history vs true AI memory

The page keeps your conversation on screen, but that is display state only.
AI-1 remains backend-stateless: each message is one independent request, and
nothing is stored in a database or localStorage. Real conversation memory is
AI-2.

## 9. AbortController

The Stop button aborts the in-flight request. Partial text stays, no scary
error appears, and the next message works normally.

## 10. Structured-output experiment

`backend/ai_labs/structured_output/` explores the optional `CopilotInsight`
schema (summary, severity, findings, recommended actions) and how the course's
`ProviderStrategy`/`ToolStrategy` map to the pinned stack.

## 11. ProviderStrategy vs ToolStrategy

On our stack the course's ProviderStrategy maps to `with_structured_output(
method="json_schema")` (provider-native) and ToolStrategy maps to
`method="function_calling"` (a synthetic tool call). OpenAI supports the
native path; Anthropic/Groq/OpenRouter often need the synthetic one. The lab
documents the per-provider recommendation. `CopilotInsight` stays optional and
learning-only for now.

## 12. create_agent vs manual loop

`backend/ai_labs/create_agent_vs_manual/` runs the same fake model + tool
through a hand-written loop and `create_agent`. Both produce the same answer;
the lab shows everything `create_agent` abstracts (message lifecycle, tool
dispatch, termination, streaming hooks).

## 13. Security visible from the UI

The UI shows a "Read-only" badge, only the tools your role can use (role-aware
example questions), and safe "unavailable" pills for denied tools. Nothing
renders SQL, tool arguments, raw results, or identity details.

## 14. How to run ICE Copilot

1. `docker compose up -d` (backend on `:8000`, DB/Redis).
2. `cd frontend && npm run dev` (SPA on `:5173`).
3. Log in, open the **ICE Copilot** page, ask a question.

## 15. What AI-1 can now do

An authenticated user can chat with a read-only copilot that answers about
their permitted projects — health, budget, inventory, purchase orders,
notifications — streamed live, with tool activity, grounded in real data.

## 16. What AI-1 deliberately cannot do

No memory across turns, no web search, no mutations, no summarization, no
retry/fallback/PII/limit middleware, no RAG, no MCP, no multi-agent. All of
those are future milestones.

## 17. What AI-2 will add

Real conversation intelligence: checkpointing (`InMemorySaver` + `thread_id`),
conversation/project context in the agent state, summarization, and
context-editing experiments.

---

# Runtime-context hardening note (post-AI-1.3 live testing)

## 1. Warning observed

During a real Copilot run, Docker backend logs showed a Pydantic warning:

```
Pydantic serializer warnings:
Expected `none` but got `ActorContext`
```

The Copilot kept working (tools ran, OpenRouter returned 200), but the warning
needed a real fix — not a suppression.

## 2. Root cause

Identity was injected by manually building `Runtime(context=actor)` and stuffing
it under an internal LangGraph key (`CONFIG_KEY_RUNTIME`), and the tools
declared their hidden param as `runtime: ToolRuntime` (untyped). When
langchain-core serializes a tool's injected arguments, the untyped `context`
field does not match its declared type, so Pydantic emitted the warning on every
tool call.

## 3. Internal vs public runtime-context mechanism

- **OLD / internal:** `config["configurable"][CONFIG_KEY_RUNTIME] = Runtime(context=actor)`.
  Works, but it reaches into LangGraph internals and produced the warning with
  untyped tool params.
- **PUBLIC LangChain v1 API (now used):** `create_agent(..., context_schema=ActorContext)`
  and pass `context=actor` to `astream`/`ainvoke`. Tools type their hidden
  param as `runtime: ToolRuntime[ActorContext]`.

## 4. Why `context_schema` matters

It tells LangChain the exact type of the runtime context, so `ToolRuntime.context`
is typed as `ActorContext` and the serializer no longer warns. It is the
supported, version-safe way to inject authenticated identity.

## 5. Final recommended ToolRuntime pattern

```
create_agent(model, tools, system_prompt, context_schema=ActorContext)
agent.astream({"messages": [...]}, context=actor, stream_mode=[...])
async def tool(..., runtime: ToolRuntime[ActorContext]) -> ...
```

Identity still flows: HTTP user → ActorContext → runtime context →
ToolRuntime.context → tool → hard ICE authorization. Identity stays hidden from
model-visible tool schemas.

## 6. Repeated-health-call observation (learning, NOT optimized)

For *"Which projects need attention?"*, the live agent showed:

```
Checking Projects...
Checking Project health...  (×12)
```

That is the expected **N+1 agent/tool pattern**: `list_projects` first, then
one `get_project_health` call per project. It is NOT a loop defect — the model
iterates the returned projects. It consumes many model/tool calls and tokens.
This is a deliberate future experiment for **AI-5 (tool architecture /
portfolio-level tools)** — do not optimize the AI-1 tool catalog for it yet.

---

# How to inspect an ICE Copilot run

Every Copilot request writes structured execution logs (safe, observable
tracing — never chain-of-thought). Here is the flow and how to read the logs.

## 1. The request flow

1. Request enters FastAPI (`POST /assistant/chat`, authenticated).
2. An immutable `ActorContext(user_id, role)` is built from the logged-in user.
3. The role's allowed tools are selected (defense-in-depth; each tool still
   re-checks permissions itself).
4. The model receives the user message + the tool schemas + system prompt.
5. The model may request a tool (`AIMessage.tool_calls`).
6. `ToolRuntime` injects the actor into the tool (identity is never a tool
   argument).
7. The tool rechecks RBAC, then runs and returns a `ToolMessage`.
8. The loop continues until the model gives a final `AIMessage`.
9. The final answer streams to the browser as SSE events.
10. A run summary records tokens / calls / timing.

## 2. Execution logs != chain-of-thought

Logs describe WHAT happened (which model call, which tool, what was returned,
how long, how many tokens). They never contain the model's private reasoning,
system-prompt contents, secrets, raw SQL, or full data dumps.

## 3. Normal vs debug mode

- **Normal (always on):** concise `event=... request_id=...` lines —
  `assistant.run.started`, `assistant.model.completed`,
  `assistant.tool.started`/`assistant.tool.completed`,
  `assistant.authorization.denied`, `assistant.stream.completed`,
  `assistant.run.completed` (metrics), `assistant.run.failed`.
- **Debug (`ICE_AI_DEBUG=true`):** adds the sanitized query, available tools,
  tool arguments, safe result summaries, and the message-type sequence
  (`SystemMessage`, `AIMessage(tool_calls=1)`, `ToolMessage(tool=...)`).

## 4. Example (debug) run

```
event=assistant.run.started request_id=5ac... actor_role=admin provider=groq
  model=llama-3.1-8b-instant tool_count=7 query="which projects need attention"
event=assistant.model.started ... model_call_number=1 messages=[SystemMessage, HumanMessage]
event=assistant.model.completed ... model_call_number=1 tool_calls_requested=1
event=assistant.tool.started ... tool=list_projects
event=assistant.tool.completed ... tool=list_projects ok=True returned_count=12
event=assistant.model.started ... model_call_number=2 messages=[..., AIMessage(tool_calls=1), ToolMessage(tool=list_projects)]
event=assistant.stream.completed ... token_event_count=913 response_chars=2041
event=assistant.run.tool_counts ... list_projects=1 get_project_health=12
event=assistant.run.completed ... model_calls=14 tool_calls=13 total_tokens=6371 duration_ms=19811 result=success
```

The `assistant.run.tool_counts` line makes the **N+1 pattern** observable
(`list_projects=1` + `get_project_health=12` for a portfolio question) — a
future AI-5 optimization experiment, not fixed in AI-1.
