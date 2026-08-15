"""ICE Copilot tool registry (AI-1).

Exactly the seven approved read-only tools. The registry is the single source
both the agent harness and the per-role allow-list read.
"""
from __future__ import annotations

from typing import Any

from app.ai.tools.finance import get_project_budget
from app.ai.tools.health import get_project_health
from app.ai.tools.inventory import get_project_inventory
from app.ai.tools.notifications import get_my_notifications
from app.ai.tools.procurement import get_purchase_orders
from app.ai.tools.projects import get_project, list_projects

ALL_TOOLS: list[Any] = [
    list_projects,
    get_project,
    get_project_health,
    get_project_budget,
    get_project_inventory,
    get_purchase_orders,
    get_my_notifications,
]

TOOL_BY_NAME: dict[str, Any] = {tool.name: tool for tool in ALL_TOOLS}
