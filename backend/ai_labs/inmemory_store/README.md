# CONTEXT vs STATE vs STORE

**LEARNING ONLY** — no network, no DB.

## The three layers

| Layer | What it is | Lifetime |
|---|---|---|
| CONTEXT (ActorContext) | who is calling NOW (immutable, injected) | per invocation |
| STATE (InMemorySaver) | what happened in THIS thread (messages) | per thread |
| STORE (InMemoryStore) | data shared ACROSS threads (namespaced) | process-local |

## Experiment (`inmemory_store_demo.py`)

A user preference `report_format = concise` is stored from Thread A and read in
Thread B by the SAME user (`user:{alice}` namespace), while a DIFFERENT user
(`user:{bob}`) using the SAME external thread id reads `None`.

## Conclusions

- The store namespace is user-scoped exactly like thread keys — cross-user
  isolation holds.
- The store is **process-local** (like InMemorySaver): it resets on restart and
  is not shared across backend workers.
- The store is NEVER used for authorization — identity stays in ActorContext →
  ToolRuntime.context.
- ICE product does not add InMemoryStore in W7.4; the experiment proves the
  mechanism only.
