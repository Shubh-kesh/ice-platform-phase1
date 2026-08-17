"""LEARNING ONLY — never imported by app/, no network, no DB.

"Make me a weekly report" — a structured-output workflow that ICE Copilot can
run with ONLY read-only tools (project, health, tasks, site logs, budget,
inventory, POs). Read-only means NO HITL is needed.

This lab simulates the data-gathering step with deterministic fixtures and
demonstrates the STRUCTURED OUTPUT step: the model's reply is validated against
a ProjectWeeklyReport schema (a typed Pydantic model), exactly like the
Weekend-07 structured-output lesson. Product integration would call the real
read-only ICE tools instead of the fixtures and a real provider instead of the
fake.

Run:  python3 report_workflow_demo.py
"""
from __future__ import annotations

import json

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel, Field

# --- the structured report contract -----------------------------------------


class ProjectWeeklyReport(BaseModel):
    project: str
    executive_summary: str = Field(description="2-3 sentence summary")
    schedule: str = Field(description="schedule status vs plan")
    health: str = Field(description="computed health signal")
    budget: str = Field(description="budget vs spend")
    inventory: str = Field(description="material availability")
    procurement: str = Field(description="open POs / deliveries")
    site_activity: str = Field(description="recent daily site log highlights")
    risks: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)


class FakeStructuredModel(BaseChatModel):
    """Self-contained fake returning a schema-shaped JSON report."""

    payload: str

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.payload))])

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self):
        return "fake-report"


# Simulated read-only tool results for Green Heights (fixtures — not live data).
TOOL_RESULTS = {
    "get_project_health": {"health": "healthy", "score": 78},
    "get_project_tasks": {"items": [{"name": "Slab pour", "status": "in_progress", "percent_complete": 60}, {"name": "Foundation inspection", "status": "pending"}]},
    "get_project_budget": {"budget_total": 1000000, "budget_spent": 412000},
    "get_project_inventory": {"items": [{"name": "Cement", "quantity_on_hand": 420}, {"name": "Steel", "quantity_on_hand": 12}]},
    "get_purchase_orders": {"items": [{"po_number": "PO-1042", "status": "open", "amount": 85000}]},
    "get_daily_site_logs": {"items": [{"log_date": "2026-08-14", "work_summary": "Cement stacking and rebar cutting"}, {"log_date": "2026-08-13", "work_summary": "Site clearance and survey"}]},
}


def gather() -> dict:
    """Deterministic stand-in for the agent's read-only tool calls."""
    return {
        "health": TOOL_RESULTS["get_project_health"]["health"],
        "tasks": "; ".join(f"{t['name']} ({t['status']})" for t in TOOL_RESULTS["get_project_tasks"]["items"]),
        "budget": f"spent {TOOL_RESULTS['get_project_budget']['budget_spent']} of {TOOL_RESULTS['get_project_budget']['budget_total']}",
        "inventory": "Cement 420 bags; Steel 12t",
        "po": "PO-1042 open (Rs 85,000)",
        "site": "Slab pour in progress; rebar cutting on 14 Aug",
    }


def main() -> None:
    data = gather()
    print("=" * 74)
    print("READ-ONLY data gathered (simulated tools, no HITL required)")
    print("=" * 74)
    for key, value in data.items():
        print(f"  {key}: {value}")

    # The structured model's reply — schema-shaped JSON (deterministic).
    report_json = json.dumps(
        {
            "project": "Green Heights",
            "executive_summary": "Green Heights is healthy (score 78). Slab pour is in progress; budget is under spend and materials are adequate.",
            "schedule": "On track; slab pour 60% complete.",
            "health": "healthy",
            "budget": "spent 412000 of 1000000",
            "inventory": "Cement 420 bags; Steel 12t — adequate for the next two weeks.",
            "procurement": "PO-1042 open (Rs 85,000); no delivery logged this week.",
            "site_activity": "Site clearance, rebar cutting and cement stacking logged 13-14 Aug.",
            "risks": ["Steel stock could dip if PO-1042 delivery slips."],
            "recommended_actions": ["Expedite PO-1042 delivery", "Schedule the foundation inspection"],
        }
    )
    model = FakeStructuredModel(payload=report_json)
    reply = model.invoke([("user", "Make me a weekly report for Green Heights")])

    print()
    print("=" * 74)
    print("STRUCTURED OUTPUT — validated against ProjectWeeklyReport")
    print("=" * 74)
    parsed = ProjectWeeklyReport.model_validate_json(str(reply.content))
    for section, value in parsed.model_dump().items():
        if isinstance(value, list):
            print(f"  {section}:")
            for item in value:
                print(f"    - {item}")
        else:
            print(f"  {section}: {value}")
    print()
    print("Validated Pydantic instance:", type(parsed).__name__)


if __name__ == "__main__":
    main()
