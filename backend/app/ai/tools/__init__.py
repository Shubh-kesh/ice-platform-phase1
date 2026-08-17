"""ICE Copilot tool registry.

Read-only catalog (W7.3): 7 original + web_search + 7 field/billing/finance
tools = 15 tools. The registry is the single source both the agent harness and
the per-role allow-list read.
"""
from __future__ import annotations

from typing import Any

from app.ai.tools.billing import get_billing_milestones, get_invoices
from app.ai.tools.field import get_daily_site_logs, get_project_tasks
from app.ai.tools.finance import get_job_costs, get_project_budget
from app.ai.tools.health import get_project_health
from app.ai.tools.inventory import get_project_inventory, get_project_inventory_movements
from app.ai.tools.mutating import create_daily_site_log, create_task
from app.ai.tools.notifications import get_my_notifications
from app.ai.tools.procurement import get_purchase_order_deliveries, get_purchase_orders
from app.ai.tools.projects import get_project, list_projects
from app.ai.tools.web import web_search

ALL_TOOLS: list[Any] = [
    list_projects,
    get_project,
    get_project_health,
    get_project_budget,
    get_project_inventory,
    get_project_inventory_movements,
    get_purchase_orders,
    get_purchase_order_deliveries,
    get_billing_milestones,
    get_invoices,
    get_project_tasks,
    get_daily_site_logs,
    get_job_costs,
    get_my_notifications,
    web_search,
    # W7.4 controlled mutations (HITL-guarded; only surfaced to admin/supervisor
    # roles AND only when ICE_AI_MUTATIONS_ENABLED=true — see agent.py).
    create_task,
    create_daily_site_log,
]

TOOL_BY_NAME: dict[str, Any] = {tool.name: tool for tool in ALL_TOOLS}
