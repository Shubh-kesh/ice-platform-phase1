# "Make me a report" — structured output with read-only tools

**LEARNING ONLY** — no network, no DB (simulated data).

## Hypothesis

A useful ICE use case: the Copilot gathers data with read-only tools and emits a
STRUCTURED `ProjectWeeklyReport` (project, executive_summary, schedule, health,
budget, inventory, procurement, site_activity, risks, recommended_actions).
Read-only ⇒ no HITL needed.

## Experiment (`report_workflow_demo.py`)

- Deterministic stand-ins for the read-only tool results (health, tasks, budget,
  inventory, POs, site logs).
- The structured model's reply is validated against the Pydantic schema
  (`ProjectWeeklyReport.model_validate_json`) → a typed instance.

## Conclusion

Structured output makes the report reliable and machine-checkable. Product
integration would swap the fixtures for the real read-only ICE tools and a real
provider; kept as a lab in W7.4 (no PDF/file generation — the goal is
agent/structured-output learning). No HITL, no mutation.
