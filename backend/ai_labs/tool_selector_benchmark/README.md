# LLMToolSelector — cost benchmark

**LEARNING ONLY** — no network, no DB.

## Hypothesis

Sending all 15 tool schemas to the main model costs input tokens every turn. An
LLM selector model narrows to a relevant subset — but the selector itself costs
a call. Is it a net win?

## Setup

`tool_selector_benchmark_demo.py` measures the JSON-schema token proxy
(≈ chars/4) for BASELINE (all schemas) vs SELECTOR (always_include + a small
question-specific selection), including the selector's input/output tokens.

## Results (deterministic proxy)

- BASELINE main-model tool-schema tokens ~ 1735 (over the 5-question set).
- SELECTOR main-model ~ 308 + selector model ~ 430 = ~738 total.

The selector saves MAIN-model schema tokens even when its own cost is counted,
but these are PROXY numbers — a live run must confirm real savings.

## Conclusion

Measurement-gated: ICE keeps `ICE_AI_TOOL_SELECTOR_ENABLED=false` by default.
Enable only if a live benchmark confirms net savings and routing accuracy.
The selector may only NARROW the role-authorized toolset; it is never the RBAC
boundary (every selected tool still self-authorizes).
