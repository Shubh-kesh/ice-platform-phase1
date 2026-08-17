# Context editing — stored conversation vs active model context

**LEARNING ONLY** — never imported by `app/`, no network, no DB.

## Question

With a checkpointer, the full ToolMessage history is STORED in the thread. Is
that also what the model sees on the next call? Can context editing shrink the
ACTIVE model context without deleting stored history?

## Setup

`context_editing_demo.py` runs 3 turns with a mock inventory tool that returns a
large result, under:

- A. **full tool history** — saver only (every old ToolMessage sent verbatim)
- B. **ContextEditingMiddleware + ClearToolUsesEdit(keep=1)** — old tool uses
  cleared to a `[cleared]` placeholder

The fake model records its input messages (observable context only — never
chain-of-thought).

## Experiment / metrics

- model-call-2 input character count
- whether turn-1 tool content (`Item-5`) remains
- whether the `[cleared]` placeholder appears

## Observations (pinned stack)

- A: input ~1467 chars, no `[cleared]` — full history is re-sent.
- B: input ~754 chars, `[cleared]` present — old tool use cleared from the
  active context while the stored history is untouched.

## Conclusion

STORED conversation (checkpoint) and ACTIVE model context are different things.
`ContextEditingMiddleware`/`ClearToolUsesEdit` control what the model sees next,
reducing input cost, without deleting history or affecting authorization (RBAC
is per-tool from ActorContext, never stored).
