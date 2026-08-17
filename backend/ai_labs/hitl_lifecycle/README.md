# HITL lifecycle — approve / edit / reject / respond

**LEARNING ONLY** — no network, no DB (simulated tool).

## Hypothesis

HumanInTheLoopMiddleware interrupts a proposed mutating tool call; the graph
pauses at a checkpoint; `Command(resume={"decisions": [...]})` continues it.

## Lifecycle (observable, `hitl_lifecycle_demo.py`)

1. `AIMessage(tool_call)` — the model proposes the action.
2. Interrupt — `__interrupt__` in the result; checkpoint `next` =
   `HumanInTheLoopMiddleware.after_model`, `interrupts=1`.
3. Human decision → `Command(resume=...)`.
4. `ToolMessage` → final `AIMessage`.

| Decision | Result |
|---|---|
| approve | tool executes with the ORIGINAL args (1 run) |
| edit | tool executes with the EDITED args (1 run) |
| reject | tool never executes; `ToolMessage(status="error")` |
| respond | tool never executes; the human's message is returned as the tool result (`status="success"`) |

## Conclusion

Approve runs the proposal; edit runs only the edited values; reject/respond
never execute the tool. Before the decision the graph is paused, so the
underlying (ICE) mutation is guaranteed not to have happened. HITL is an
ADDITIONAL control layer — the tool still self-authorizes from
`ToolRuntime.context` after approval.
