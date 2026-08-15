# create_agent vs manual loop

**LEARNING ONLY** — never imported by `app/`, no network, no DB.

## Question

What does LangChain's `create_agent` actually abstract compared with the
hand-written agentic loop from Class 05?

## Setup

`create_agent_vs_manual_demo.py` runs the SAME fake model + the SAME mock
tool + the SAME question through:

1. a **manual loop** (`manual_loop`): you build messages, call the model,
   detect `tool_calls`, dispatch each tool, append `ToolMessage`s, and guard
   termination yourself;
2. **`create_agent`**: the harness does all of that.

The fake model records how many messages each model call saw.

## Observation

Both produced the identical answer and identical model-call sequences
(`[2, 4]` messages). The difference is purely orchestration ownership.

## Expected learning

`create_agent` abstracts tool-schema binding, the Human/AI/Tool message
lifecycle, tool dispatch, loop-back, termination, system-prompt injection,
ToolRuntime injection and streaming/checkpoint hooks. ICE uses `create_agent`
in production; the manual loop is a learning reference only.
