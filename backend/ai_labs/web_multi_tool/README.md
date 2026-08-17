# Web multi-tool — sequential vs parallel tool calling

**LEARNING ONLY** — never imported by `app/`, no network, no DB.

## Hypothesis

Parallel tool calls are faster than sequential when the tools are independent;
sequential is required when one tool's input depends on another's output.

## Setup

`web_multi_tool_demo.py` answers "cement on hand + market price?" with a fake
model + mock `get_inventory` (0.2s) and `web_search` (0.3s) tools:

- **PARALLEL**: both tool calls in one model turn (LangChain runs the tool node
  concurrently).
- **SEQUENTIAL**: inventory first, then a web query informed by the inventory
  result (extra model turn).

## Expected behavior / metrics

- Parallel: ~max(0.2, 0.3) + 1 model call.
- Sequential: ~0.2 + 0.3 + 2 model calls (each tool needs its own turn).

## Observations

Parallel is faster and cheaper for independent calls; sequential is correct
when tool B's arguments depend on tool A's output. ICE uses both naturally:
"inventory + market price" can be parallel; "what is the market price of the
steel we actually have on PO" is inherently sequential.

## Conclusion

Do not claim parallel is always better — match the dependency graph.
