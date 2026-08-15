# Agent loop — observable message flow experiment

**LEARNING ONLY** — never imported by `app/`, no network, no DB.

## Question

What exactly happens between "user message in" and "final answer out" in a
`create_agent` loop?

## Hypothesis

The loop is: HumanMessage → model sees tools → AIMessage with a tool call →
tool executes → ToolMessage → model continues → final AIMessage. The model is
called more than once, and each call's input messages grow.

## Setup

`agent_loop_demo.py` builds a real `create_agent` with a fake `LoopRecordingModel`
(records every input it receives) and one mock tool. It prints:

1. the messages before the first model call,
2. the tool schema the model sees,
3. the full message timeline after the run,
4. exactly what was sent to each model call (the ToolMessage appears in call #2),
5. the final AIMessage with usage metadata.

Run: `python3 agent_loop_demo.py` (needs langchain; no key, no network).

## Metric / observation

- call #1 input = `[HumanMessage]`
- call #2 input = `[HumanMessage, AIMessage(tool_call), ToolMessage]`
- final = `AIMessage` (with `usage_metadata` from the provider-shaped fake).

## Expected learning

Tool calling is a loop, not one response; the harness feeds tool results back as
`ToolMessage`s. The ICE Copilot translates these mechanics into a stable SSE
event contract (`app/ai/agent.py::stream_assistant`).

## Conclusion

LEARNING (mechanism inspection only — no hidden chain-of-thought; public
LangChain message/tool mechanics).
