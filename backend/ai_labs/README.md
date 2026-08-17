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
- `memory_compare/` — stateless vs InMemorySaver(+thread_id) vs
  SummarizationMiddleware on the observable message flow (W7.1).
- `context_editing/` — stored conversation vs active model context:
  ContextEditingMiddleware/ClearToolUsesEdit (W7.1).
- `web_multi_tool/` — sequential vs parallel tool calling with ICE + web tools
  (W7.2).
- `retry_backoff/` — ToolRetryMiddleware exponential-backoff timing (W7.2).
- `middleware_order/` — does middleware order matter? (W7.3)
- `model_resilience/` — model retry vs fallback (W7.3).
- `pii/` — PII strategies + custom Aadhaar/PAN detectors (W7.3).
- `tool_error/` — safe_tool vs ToolErrorMiddleware (W7.3).
- `todo_middleware/` — TodoListMiddleware planning tool (W7.3).
- `tool_selector_benchmark/` — tool-schema cost proxy (W7.3).
- `hitl_lifecycle/` — approve / edit / reject / respond lifecycle (W7.4).
- `llm_tool_emulator/` — emulated sensitive decision paths, zero DB writes (W7.4).
- `inmemory_store/` — context vs state vs store (W7.4).
- `return_direct/` — skip the extra model call (W7.4).
- `tool_gating/` — dynamic tool gating via wrap_model_call (W7.4).
- `report_workflow/` — structured "make me a report" with read-only tools (W7.4).
