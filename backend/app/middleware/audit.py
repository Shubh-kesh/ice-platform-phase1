"""
Lightweight audit trail helper.

This is intentionally a plain function rather than magic ORM event hooks —
explicit calls at the point of mutation are easier to reason about and audit
in a financial system than implicit `after_update` listeners. Call this from
any endpoint that creates, updates, or deletes a record that must be
traceable (users, projects, and — in Phase 2 — every inventory and finance
write).
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog


async def record_audit(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    action: str,
    table_name: str,
    record_id: str,
    changes: dict,
    ip_address: str | None = None,
) -> None:
    entry = AuditLog(
        user_id=user_id,
        action=action,
        table_name=table_name,
        record_id=record_id,
        changes=changes,
        ip_address=ip_address,
    )
    db.add(entry)
    # Deliberately no commit here — caller commits alongside the actual
    # data change so both succeed or fail together in one transaction.
