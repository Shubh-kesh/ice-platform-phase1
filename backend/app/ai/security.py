"""
ICE Copilot security layer.

The HARD boundary is per-tool deterministic authorization: every tool checks
the authenticated actor against the same role/project rules the REST API
enforces. The per-role allow-list below is DEFENSE IN DEPTH only — it prunes
the tool menu the model sees, but a tool that somehow reaches the model still
rejects unauthorized access on its own.

The model can never supply identity facts: tools read them from
`ToolRuntime.context` (the injected ActorContext), never from arguments.
"""
from __future__ import annotations

from app.models.user import UserRole

# The seven AI-1 tool names (single source shared by the registry and tests).
TOOL_LIST_PROJECTS = "list_projects"
TOOL_GET_PROJECT = "get_project"
TOOL_GET_PROJECT_HEALTH = "get_project_health"
TOOL_GET_PROJECT_BUDGET = "get_project_budget"
TOOL_GET_PROJECT_INVENTORY = "get_project_inventory"
TOOL_GET_PURCHASE_ORDERS = "get_purchase_orders"
TOOL_GET_MY_NOTIFICATIONS = "get_my_notifications"
TOOL_WEB_SEARCH = "web_search"
# W7.3 expanded read-only catalog.
TOOL_GET_PROJECT_TASKS = "get_project_tasks"
TOOL_GET_DAILY_SITE_LOGS = "get_daily_site_logs"
TOOL_GET_JOB_COSTS = "get_job_costs"
TOOL_GET_INVENTORY_MOVEMENTS = "get_project_inventory_movements"
TOOL_GET_PO_DELIVERIES = "get_purchase_order_deliveries"
TOOL_GET_BILLING_MILESTONES = "get_billing_milestones"
TOOL_GET_INVOICES = "get_invoices"
# W7.4 controlled mutations (HITL-guarded, low-risk first).
TOOL_CREATE_TASK = "create_task"
TOOL_CREATE_DAILY_SITE_LOG = "create_daily_site_log"

_ALL_TOOLS = frozenset(
    {
        TOOL_LIST_PROJECTS,
        TOOL_GET_PROJECT,
        TOOL_GET_PROJECT_HEALTH,
        TOOL_GET_PROJECT_BUDGET,
        TOOL_GET_PROJECT_INVENTORY,
        TOOL_GET_PURCHASE_ORDERS,
        TOOL_GET_MY_NOTIFICATIONS,
        TOOL_WEB_SEARCH,
        TOOL_GET_PROJECT_TASKS,
        TOOL_GET_DAILY_SITE_LOGS,
        TOOL_GET_JOB_COSTS,
        TOOL_GET_INVENTORY_MOVEMENTS,
        TOOL_GET_PO_DELIVERIES,
        TOOL_GET_BILLING_MILESTONES,
        TOOL_GET_INVOICES,
        TOOL_CREATE_TASK,
        TOOL_CREATE_DAILY_SITE_LOG,
    }
)

# The mutating tools (W7.4). Each requires HITL approval before execution; the
# per-tool RBAC below mirrors the REST `write_roles` (admin + site supervisor).
MUTATING_TOOLS = frozenset({TOOL_CREATE_TASK, TOOL_CREATE_DAILY_SITE_LOG})

# Exact REST-equivalent tool menu per role (mirrors the route role gates; see
# the RBAC matrix in the AI-1 plan §10). Clients only ever get the M6 client
# portal surfaces: projects (restricted shape) + their own notifications.
ROLE_ALLOWED_TOOLS: dict[UserRole, frozenset[str]] = {
    UserRole.ADMIN: _ALL_TOOLS,
    # Procurement mirrors REST: admin writes tasks/site logs, procurement does
    # NOT (its write surface is procurement/finance only).
    UserRole.PROCUREMENT_MANAGER: _ALL_TOOLS - MUTATING_TOOLS,
    UserRole.SITE_SUPERVISOR: frozenset(
        {
            TOOL_LIST_PROJECTS,
            TOOL_GET_PROJECT,
            TOOL_GET_PROJECT_HEALTH,
            TOOL_GET_PROJECT_INVENTORY,
            TOOL_GET_INVENTORY_MOVEMENTS,
            TOOL_GET_PROJECT_TASKS,
            TOOL_GET_DAILY_SITE_LOGS,
            TOOL_GET_MY_NOTIFICATIONS,
            TOOL_WEB_SEARCH,
            TOOL_CREATE_TASK,
            TOOL_CREATE_DAILY_SITE_LOG,
        }
    ),
    UserRole.CLIENT: frozenset(
        {
            TOOL_LIST_PROJECTS,
            TOOL_GET_PROJECT,
            TOOL_GET_PROJECT_TASKS,
            TOOL_GET_DAILY_SITE_LOGS,
            TOOL_GET_INVOICES,
            TOOL_GET_MY_NOTIFICATIONS,
            TOOL_WEB_SEARCH,
        }
    ),
}


class ToolError(Exception):
    """Base class for controlled ICE Copilot tool failures."""


class ToolForbidden(ToolError):
    """The actor is not permitted to perform this operation (REST 403-equiv)."""


class ToolNotFound(ToolError):
    """The requested entity does not exist or is not visible (REST 404-equiv)."""


def tools_for_role(role: UserRole) -> frozenset[str]:
    """Names of the tools this role may be given (defense in depth)."""
    return ROLE_ALLOWED_TOOLS[role]


def assert_tool_allowed(role: UserRole, tool_name: str) -> None:
    """Reject tool calls whose name is outside the role's menu.

    Defense-in-depth only — each tool re-authorizes internally regardless.
    """
    if tool_name not in tools_for_role(role):
        raise ToolForbidden(f"Tool '{tool_name}' is not permitted for role '{role.value}'")
