# Dynamic tool gating (wrap_model_call)

**LEARNING ONLY** — no network, no DB.

## Hypothesis

The role-filtered catalog already prunes the model's menu statically. Dynamic
gating via `wrap_model_call` can additionally hide tools per request (defense in
depth / token reduction) — it is NOT authorization.

## Experiment (`tool_gating_demo.py`)

- STATIC: both `list_projects` + `get_project_budget` bound and visible.
- DYNAMIC: a `wrap_model_call` middleware removes `get_project_budget` for a
  "client" request → the model sees only `['list_projects']`.

## Conclusion

Dynamic gating shrinks what the model can propose, but the FINAL authorization
boundary stays the tool's own self-check from `ToolRuntime.context`. ICE already
achieves role-based pruning statically; this is a concise lab, not product
duplication. (Pinned-version note: the wrapped async function receives
`(request, handler)` and must be async for `ainvoke`.)
