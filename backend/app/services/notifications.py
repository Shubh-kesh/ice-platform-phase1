"""
In-app notification service (Phase 3, M13).

Centralizes notification creation so event hooks stay thin and consistent:

  * notifications are created in the **caller's transaction** (atomic with the
    triggering business event — a rolled-back event creates no notifications);
  * recipient resolution reuses the existing role/assignment model (never a new
    authorization system);
  * bodies carry minimal content (no secrets, no financial detail beyond what
    the recipient may already see);
  * low-stock uses deterministic transition detection (old > threshold and new
    <= threshold) so a repeated/retried operation never stacks duplicates.

No worker, queue, or external provider — M13 is in-app only.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationType
from app.models.project import ProjectAssignment
from app.models.user import User, UserRole

# Roles that receive each notification type (admins are always included).
# Supervisors and clients are project-assignable; procurement managers are not
# (they see every project by role, so low-stock alerts use global resolution).
_SCHEDULE_ROLES = (UserRole.SITE_SUPERVISOR,)
_INVOICE_ROLES = (UserRole.CLIENT,)
_LOW_STOCK_ROLES = (UserRole.PROCUREMENT_MANAGER,)


async def project_role_recipient_ids(
    db: AsyncSession,
    project_id: uuid.UUID,
    roles: tuple[UserRole, ...],
    include_admins: bool = True,
) -> list[uuid.UUID]:
    """Assigned users of `project_id` whose role is in `roles`, plus (optionally)
    every active admin. Deduplicated; respects the project-assignment model."""
    recipient_ids: set[uuid.UUID] = set()

    result = await db.execute(
        select(User.id)
        .join(ProjectAssignment, ProjectAssignment.user_id == User.id)
        .where(
            ProjectAssignment.project_id == project_id,
            User.role.in_(roles),
            User.is_active.is_(True),
        )
    )
    recipient_ids.update(result.scalars().all())

    if include_admins:
        recipient_ids.update(await _active_admin_ids(db))

    return list(recipient_ids)


async def global_role_recipient_ids(
    db: AsyncSession, roles: tuple[UserRole, ...], include_admins: bool = True
) -> list[uuid.UUID]:
    """Every active user of `roles` (global-visibility roles such as
    procurement), plus optionally admins."""
    recipient_ids: set[uuid.UUID] = set()

    result = await db.execute(
        select(User.id).where(User.role.in_(roles), User.is_active.is_(True))
    )
    recipient_ids.update(result.scalars().all())

    if include_admins:
        recipient_ids.update(await _active_admin_ids(db))

    return list(recipient_ids)


async def _active_admin_ids(db: AsyncSession) -> list[uuid.UUID]:
    admins = await db.execute(
        select(User.id).where(User.role == UserRole.ADMIN, User.is_active.is_(True))
    )
    return list(admins.scalars().all())


async def create_notifications(
    db: AsyncSession,
    *,
    user_ids: list[uuid.UUID],
    project_id: uuid.UUID | None,
    type_: NotificationType,
    title: str,
    body: str,
    link: str | None = None,
) -> None:
    """Insert one notification per recipient in the caller's transaction.

    Never commits — the caller commits alongside the triggering event so both
    succeed or fail together. Duplicate user_ids are collapsed.
    """
    for user_id in dict.fromkeys(user_ids):
        db.add(
            Notification(
                user_id=user_id,
                project_id=project_id,
                type=type_,
                title=title,
                body=body,
                link=link,
            )
        )


async def notify_schedule_shift(db: AsyncSession, project_id: uuid.UUID, shift_count: int) -> None:
    """M12 schedule cascade -> project supervisors + admins."""
    recipients = await project_role_recipient_ids(db, project_id, _SCHEDULE_ROLES)
    await create_notifications(
        db,
        user_ids=recipients,
        project_id=project_id,
        type_=NotificationType.TASK_SCHEDULE_SHIFT,
        title="Schedule updated",
        body=f"{shift_count} task(s) shifted to keep dependencies valid",
        link=f"/projects/{project_id}",
    )


async def notify_invoice_issued(
    db: AsyncSession, project_id: uuid.UUID, invoice_number: str
) -> None:
    """M5 invoice DRAFT->SENT -> assigned client + admins (a payment request)."""
    recipients = await project_role_recipient_ids(db, project_id, _INVOICE_ROLES)
    await create_notifications(
        db,
        user_ids=recipients,
        project_id=project_id,
        type_=NotificationType.MILESTONE_INVOICE_ISSUED,
        title="Payment request issued",
        body=f"Payment request {invoice_number} has been issued",
        link=f"/projects/{project_id}",
    )


async def notify_low_stock(
    db: AsyncSession,
    project_id: uuid.UUID,
    item_name: str,
    unit: str,
    quantity: float,
) -> None:
    """Inventory at/below reorder threshold -> procurement + admins.

    Callers only invoke this when the balance *crossed* the threshold (old >
    threshold and new <= threshold), so repeated movements/retries cannot stack
    duplicate alerts.
    """
    recipients = await global_role_recipient_ids(db, _LOW_STOCK_ROLES)
    await create_notifications(
        db,
        user_ids=recipients,
        project_id=project_id,
        type_=NotificationType.INVENTORY_LOW_STOCK,
        title="Low stock",
        body=f"{item_name} is low: {quantity:g} {unit} remaining",
        link=f"/projects/{project_id}",
    )


async def notify_project_assigned(
    db: AsyncSession,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    project_name: str,
) -> None:
    """M2 assignment -> the newly assigned supervisor/client."""
    await create_notifications(
        db,
        user_ids=[user_id],
        project_id=project_id,
        type_=NotificationType.PROJECT_ASSIGNED,
        title="Project access granted",
        body=f"You now have access to {project_name}",
        link=f"/projects/{project_id}",
    )
