# ToolRuntime context — identity injection experiment

**LEARNING ONLY** — never imported by `app/`, no network, no DB.

## Question

Where should authenticated identity (user_id, role) live so that an LLM can
never spoof it, and what is the SUPPORTED LangChain v1 mechanism for injecting
it?

## Findings (pinned stack: langchain 1.3.15 / langgraph 1.2.11)

**Part A — schema:** identity as an ordinary tool argument is model-visible and
spoofable. With `runtime: ToolRuntime[...]`, LangChain auto-hides the runtime
param from the model-facing `.args` schema.

**Part B — mechanism (this is the important one):**

- **OLD / internal:** build `Runtime(context=actor)` and stuff it under
  `config["configurable"][CONFIG_KEY_RUNTIME]`. With an **untyped**
  `runtime: ToolRuntime` tool param this produced the Pydantic serializer
  warning `Expected `none` but got `ActorContext`` (langchain-core serializes
  the tool's injected args and the untyped `context` field doesn't match).
- **PUBLIC LangChain v1 API (recommended):**
  `create_agent(..., context_schema=ActorContext)` and invoke with
  `context=actor`. Tools type the param as `runtime: ToolRuntime[ActorContext]`.
  Result: ToolRuntime.context carries the ActorContext and **no serializer
  warning** (0 warnings in the demo).

## Run

`python3 toolruntime_context_demo.py` — prints both schemas, both mechanisms,
and the warning counts.

## Conclusion

PRODUCT rules:
1. Identity is injected via runtime/application context, never an argument.
2. Use the public `context_schema` + `context=` API (not the internal
   `CONFIG_KEY_RUNTIME`), and type tool params as `ToolRuntime[ActorContext]`.
3. Tools independently re-authorize from that context.
