# LLMToolEmulator — sensitive decision paths with zero risk

**LEARNING / SIMULATION ONLY** — no ICE data is written.

## Hypothesis

A sensitive mutating tool (`receive_purchase_order` — NOT enabled in ICE) can
be EMULATED so the agent exercises its full decision path (tool selection,
arguments, downstream response) while the real function never runs.

## Setup

`llm_tool_emulator_demo.py`: the main (fake) model proposes
`receive_purchase_order`; `LLMToolEmulator(tools=["receive_purchase_order"],
model=...)` replaces the real call with a SYNTHETIC result.

## Results

- Tool selected, real args passed to the emulator prompt.
- Synthetic result returned (clearly marked `simulated: true`).
- Real function executions = **0**.

## Conclusion

Emulate BEFORE enabling: validate the agent's decision path with zero risk, then
decide whether to wire the real HITL-protected tool. Never present an emulated
result as a real mutation.
