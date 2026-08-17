"""LEARNING ONLY — never imported by app/, no network, no DB.

LLMToolSelector cost benchmark.

The dominant input cost driver for the MAIN model is the serialized tool
schemas it is given. This demo compares:

  BASELINE : all role-allowed tool schemas sent to the main model
  SELECTOR : a small selection (always_include + max_tools) sent instead,
             after an LLM selector model chooses the relevant subset

We measure the JSON-schema byte/token PROXY (approximate tokens ~ chars/4)
for each option. The selector's own input/output tokens are added to its side.
This is a deterministic proxy — a live run must confirm real token savings.

Run:  python3 tool_selector_benchmark_demo.py
"""
from __future__ import annotations

import json

# Self-contained: approximate each tool's model-visible schema JSON size.
# (Real sizes come from `tool.args` at runtime; this is a deterministic proxy.)
TOOL_SCHEMA_CHARS = {
    "list_projects": 80, "get_project": 90, "get_project_health": 80,
    "get_project_budget": 80, "get_project_inventory": 80, "get_project_inventory_movements": 110,
    "get_purchase_orders": 120, "get_purchase_order_deliveries": 100,
    "get_billing_milestones": 90, "get_invoices": 90, "get_project_tasks": 90,
    "get_daily_site_logs": 90, "get_job_costs": 110, "get_my_notifications": 80, "web_search": 100,
}
ALL_NAMES = sorted(TOOL_SCHEMA_CHARS)

ALWAYS_INCLUDE = ["list_projects", "get_project"]
MAX_TOOLS = 5

QUESTIONS = [
    "List my projects.",
    "Why is Green Heights unhealthy?",
    "What's in inventory?",
    "What POs are still open?",
    "Search current cement market pricing.",
]

# Deterministic "selector" for this demo: always_include + the question-specific
# tool we would expect the selector to pick.
SELECTION = {
    "List my projects.": ["list_projects", "get_project", "get_my_notifications"],
    "Why is Green Heights unhealthy?": ["list_projects", "get_project_health", "get_project"],
    "What's in inventory?": ["list_projects", "get_project_inventory", "get_project_inventory_movements"],
    "What POs are still open?": ["list_projects", "get_purchase_orders", "get_project"],
    "Search current cement market pricing.": ["web_search", "get_project_inventory"],
}


def _schema_chars(name: str) -> int:
    return TOOL_SCHEMA_CHARS[name]


def main() -> None:
    all_names = ALL_NAMES
    baseline_chars = sum(_schema_chars(n) for n in all_names)
    print("=" * 74)
    print(f"BASELINE: all {len(all_names)} tool schemas to the main model")
    print("=" * 74)
    print(f"  schemas: {len(all_names)} | approx tokens ~ {baseline_chars // 4}")

    total_selector = 0
    total_main = 0
    for q in QUESTIONS:
        sel = SELECTION[q]
        # selector sees ALL names (its input); we charge it a small input cost.
        selector_input = len(json.dumps(all_names)) // 4
        sel_chars = sum(_schema_chars(n) for n in sel)
        print(f"  Q: {q!r}")
        print(f"     baseline main-model tokens ~ {baseline_chars // 4}  | selector main-model tokens ~ {sel_chars // 4}")
        total_main += sel_chars // 4
        total_selector += selector_input + 3  # +3 approx output tokens

    print()
    print("=" * 74)
    print("TOTAL over the question set")
    print("=" * 74)
    print(f"  BASELINE main-model tool-schema tokens ~ {baseline_chars // 4 * len(QUESTIONS)}")
    print(f"  SELECTOR main-model tool-schema tokens ~ {total_main} + selector model ~ {total_selector}")
    print("  => selector saves MAIN-model schema tokens, but pays a selector call.")
    print("  Net benefit is NOT assumed — a live run must confirm real savings.")
    print("  ICE keeps the selector OFF by default (ICE_AI_TOOL_SELECTOR_ENABLED=false).")


if __name__ == "__main__":
    main()
