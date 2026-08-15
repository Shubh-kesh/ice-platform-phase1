# ICE AI Labs

Learning-only experiments for the Agentic AI course, kept **outside** the
application (`app/`). Nothing here is imported by `app/`, runs in production, or
touches the live database.

Each experiment lives in its own folder with a runnable script and a short
README (hypothesis, setup, metric, expected learning, PRODUCT-vs-LEARNING
conclusion). Experiments may need the LangChain stack already installed in the
dev environment; none require a provider API key or network unless stated.

## Experiments

- `toolruntime_context/` — BAD vs GOOD identity injection for LLM tools
  (identity in model-visible args vs `ToolRuntime.context`).
- `agent_loop/` — the observable `create_agent` message flow:
  HumanMessage → AIMessage(tool call) → ToolMessage → final AIMessage.
- `structured_output/` — CopilotInsight structured-output strategy mapping
  (ProviderStrategy ~ json_schema vs ToolStrategy ~ function_calling).
- `create_agent_vs_manual/` — a hand-written agentic loop compared with
  `create_agent` on the same fake model + tool.
