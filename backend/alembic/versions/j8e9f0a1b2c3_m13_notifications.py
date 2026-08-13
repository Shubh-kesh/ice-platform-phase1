"""m13 - in-app notifications

Revision ID: j8e9f0a1b2c3
Revises: i7d8e9f0a1b2
Create Date: 2026-08-13 00:00:00.000000

Adds `notifications`, the in-app notification table for M13 (event-driven
alerts for schedule shifts, client payment requests, low stock, and project
assignment).

Design (per the M13 plan):
* user-scoped ownership (FK users.id ON DELETE CASCADE) — a notification
  always belongs to exactly one recipient and is never readable by others.
* optional project reference (FK projects.id ON DELETE CASCADE) for navigation;
  no other entity columns are stored (titles/bodies carry minimal content).
* `type` is a constrained String (app-level enum) so no native enum type is
  introduced — avoids the SQLAlchemy 2.0.35 native-enum migration pitfall
  documented in SESSION_NOTES while still constraining values in the ORM.
* `read_at` NULL = unread; indexes back the per-user feed and unread count.

Downgrade drops the table + indexes (non-destructive; no existing data
depends on it).
"""
import sqlalchemy as sa
from alembic import op

revision = 'j8e9f0a1b2c3'
down_revision = 'i7d8e9f0a1b2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'notifications',
        sa.Column('id', sa.UUID(), primary_key=True),
        sa.Column(
            'user_id',
            sa.UUID(),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'project_id',
            sa.UUID(),
            sa.ForeignKey('projects.id', ondelete='CASCADE'),
            nullable=True,
        ),
        sa.Column('type', sa.String(length=50), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('body', sa.String(length=2000), nullable=False),
        sa.Column('link', sa.String(length=500), nullable=True),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        'ix_notifications_user_read', 'notifications', ['user_id', 'read_at']
    )
    op.create_index(
        'ix_notifications_user_created', 'notifications', ['user_id', 'created_at']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_notifications_user_created', table_name='notifications')
    op.drop_index('ix_notifications_user_read', table_name='notifications')
    op.drop_table('notifications')
