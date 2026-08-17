# return_direct — skip the extra model call

**LEARNING ONLY** — no network, no DB.

## Hypothesis

When a tool's result is already final/user-ready, `return_direct=True` returns
it immediately instead of routing it back through the model.

## Experiment (`return_direct_demo.py`)

| mode | model calls | final |
|---|---|---|
| return_direct=False | 2 (propose + summarize) | model's framed answer |
| return_direct=True | 1 | raw tool result |

## Conclusion

return_direct saves a model call and latency but SKIPS the model's framing,
so output tone/coverage is lost. ICE: **LEARNING ONLY** — tool results are data,
not final user copy, so do not apply globally. No ICE tool is switched to
return_direct.
