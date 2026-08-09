"""phase2 - tasks, daily_site_logs, inventory, finance scaffold

Revision ID: 8f3a1c2d9e01
Revises: 5d2e53a7df4e
Create Date: 2026-08-09 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '8f3a1c2d9e01'
down_revision: Union[str, Sequence[str], None] = '5d2e53a7df4e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- tasks (Gantt/timeline) ---
    op.create_table(
        'tasks',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column(
            'status',
            sa.Enum('NOT_STARTED', 'IN_PROGRESS', 'COMPLETED', 'BLOCKED', name='task_status'),
            nullable=False,
        ),
        sa.Column('percent_complete', sa.Integer(), nullable=False),
        sa.Column('depends_on_id', sa.UUID(), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['depends_on_id'], ['tasks.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_tasks_project_id'), 'tasks', ['project_id'])

    # --- daily_site_logs ---
    op.create_table(
        'daily_site_logs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('log_date', sa.Date(), nullable=False),
        sa.Column('work_summary', sa.Text(), nullable=False),
        sa.Column('issues', sa.Text(), nullable=True),
        sa.Column('workers_present', sa.Integer(), nullable=True),
        sa.Column('weather', sa.String(length=100), nullable=True),
        sa.Column('photo_urls', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_daily_site_logs_project_id'), 'daily_site_logs', ['project_id'])

    # --- inventory_items ---
    op.create_table(
        'inventory_items',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('unit', sa.String(length=50), nullable=False),
        sa.Column('quantity_on_hand', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('reorder_threshold', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('unit_cost', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_inventory_items_project_id'), 'inventory_items', ['project_id'])

    # --- stock_movements ---
    op.create_table(
        'stock_movements',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('item_id', sa.UUID(), nullable=False),
        sa.Column('recorded_by', sa.UUID(), nullable=True),
        sa.Column(
            'movement_type',
            sa.Enum('RECEIVED', 'CONSUMED', 'TRANSFERRED', 'ADJUSTED', name='movement_type'),
            nullable=False,
        ),
        sa.Column('quantity', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('note', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['item_id'], ['inventory_items.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['recorded_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_stock_movements_item_id'), 'stock_movements', ['item_id'])

    # --- job_costs (finance scaffold) ---
    op.create_table(
        'job_costs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('category', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('incurred_on', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_job_costs_project_id'), 'job_costs', ['project_id'])

    # --- invoices (finance scaffold) ---
    op.create_table(
        'invoices',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('milestone_name', sa.String(length=255), nullable=False),
        sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            'status',
            sa.Enum('DRAFT', 'SENT', 'PAID', 'OVERDUE', 'CANCELLED', name='invoice_status'),
            nullable=False,
        ),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('external_ref', sa.String(length=255), nullable=True),
        sa.Column(
            'external_sync_status',
            sa.Enum('NOT_SYNCED', 'SYNCED', 'SYNC_FAILED', name='external_sync_status'),
            nullable=False,
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_invoices_project_id'), 'invoices', ['project_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_invoices_project_id'), table_name='invoices')
    op.drop_table('invoices')
    op.drop_index(op.f('ix_job_costs_project_id'), table_name='job_costs')
    op.drop_table('job_costs')
    op.drop_index(op.f('ix_stock_movements_item_id'), table_name='stock_movements')
    op.drop_table('stock_movements')
    op.drop_index(op.f('ix_inventory_items_project_id'), table_name='inventory_items')
    op.drop_table('inventory_items')
    op.drop_index(op.f('ix_daily_site_logs_project_id'), table_name='daily_site_logs')
    op.drop_table('daily_site_logs')
    op.drop_index(op.f('ix_tasks_project_id'), table_name='tasks')
    op.drop_table('tasks')

    sa.Enum(name='external_sync_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='invoice_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='movement_type').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='task_status').drop(op.get_bind(), checkfirst=True)
