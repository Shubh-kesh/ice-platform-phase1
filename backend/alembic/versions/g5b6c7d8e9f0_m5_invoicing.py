"""m5 - invoicing: billing milestones + milestone-driven invoices

Revision ID: g5b6c7d8e9f0
Revises: f3a4b5c6d7e8
Create Date: 2026-08-11 16:00:00.000000

Adds billing_milestones, the schedule-of-values that drives M5 invoice
generation, and extends the Phase-2 `invoices` scaffold into the real M5
invoice/payment-request ledger: unique invoice_number, a nullable
billing_milestone_id reference, issuer/payer/canceller attribution columns,
and an internal notes column. external_ref/external_sync_status are kept for
the future QuickBooks/Xero sync and are never part of client responses.

Invoices are immutable against an archiving/COMPLETED project at the app layer;
at the DB layer the partial unique index (billing_milestone_id) WHERE status
<> 'CANCELLED' guarantees at most one non-cancelled invoice per milestone (a
double-billing guard that also covers concurrent requests that bypass the
M8 idempotency claim).

Enum-backed columns are added via op.add_column (ALTER TABLE) after the enums
are created explicitly with checkfirst — the SQLAlchemy 2.0.35
op.create_table path re-emits a non-checkfirst CREATE TYPE and fails with
DuplicateObject (see SESSION_NOTES §10).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'g5b6c7d8e9f0'
down_revision = 'f3a4b5c6d7e8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade schema."""
    billing_type = sa.Enum('PERCENTAGE', 'FIXED_AMOUNT', name='billing_type')
    billing_type.create(op.get_bind(), checkfirst=True)

    billing_milestone_status = sa.Enum(
        'NOT_STARTED', 'IN_PROGRESS', 'COMPLETED', name='billing_milestone_status'
    )
    billing_milestone_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'billing_milestones',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'project_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('projects.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('billing_percentage', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('fixed_amount', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'completed_by', postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.add_column(
        'billing_milestones',
        sa.Column('billing_type', billing_type, nullable=False),
    )
    op.add_column(
        'billing_milestones',
        sa.Column('status', billing_milestone_status, nullable=False),
    )
    op.create_foreign_key(
        'fk_billing_milestones_completed_by',
        'billing_milestones', 'users', ['completed_by'], ['id'], ondelete='SET NULL',
    )
    op.create_unique_constraint(
        'uq_billing_milestones_project_name',
        'billing_milestones', ['project_id', 'name'],
    )
    op.create_index(
        'ix_billing_milestones_project_id', 'billing_milestones', ['project_id']
    )

    # --- invoices: real M5 ledger columns ---
    # invoice_number is added nullable, backfilled for any legacy scaffold rows
    # (the table has never had an API, so in practice there are none), then
    # enforced NOT NULL + unique.
    op.add_column(
        'invoices', sa.Column('invoice_number', sa.String(length=40), nullable=True)
    )
    op.execute(
        """
        UPDATE invoices i
        SET invoice_number = 'INV-' || p.project_code || '-' || LPAD(r.seq::text, 4, '0')
        FROM (
            SELECT inv.id, inv.project_id,
                   ROW_NUMBER() OVER (ORDER BY inv.created_at, inv.id) AS seq
            FROM invoices inv
        ) r
        JOIN projects p ON p.id = r.project_id
        WHERE i.id = r.id
        """
    )
    op.alter_column('invoices', 'invoice_number', nullable=False)
    op.create_unique_constraint(
        'uq_invoices_invoice_number', 'invoices', ['invoice_number']
    )

    op.add_column(
        'invoices',
        sa.Column('billing_milestone_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column('invoices', sa.Column('notes', sa.Text(), nullable=True))
    op.add_column('invoices', sa.Column('issued_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('invoices', sa.Column('issued_by', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('invoices', sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('invoices', sa.Column('paid_by', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(
        'invoices', sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        'invoices', sa.Column('cancelled_by', postgresql.UUID(as_uuid=True), nullable=True)
    )

    op.create_foreign_key(
        'fk_invoices_billing_milestone_id',
        'invoices', 'billing_milestones', ['billing_milestone_id'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_invoices_issued_by', 'invoices', 'users', ['issued_by'], ['id'], ondelete='SET NULL'
    )
    op.create_foreign_key(
        'fk_invoices_paid_by', 'invoices', 'users', ['paid_by'], ['id'], ondelete='SET NULL'
    )
    op.create_foreign_key(
        'fk_invoices_cancelled_by',
        'invoices', 'users', ['cancelled_by'], ['id'], ondelete='SET NULL'
    )
    # Double-billing guard: one non-cancelled invoice per milestone. Enum values
    # are stored by member name, so the predicate compares against 'CANCELLED'.
    op.create_index(
        'uq_invoices_one_non_cancelled_per_milestone',
        'invoices',
        ['billing_milestone_id'],
        unique=True,
        postgresql_where=sa.text(
            "billing_milestone_id IS NOT NULL AND status <> 'CANCELLED'"
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        'uq_invoices_one_non_cancelled_per_milestone', table_name='invoices'
    )
    op.drop_constraint('fk_invoices_cancelled_by', 'invoices', type_='foreignkey')
    op.drop_constraint('fk_invoices_paid_by', 'invoices', type_='foreignkey')
    op.drop_constraint('fk_invoices_issued_by', 'invoices', type_='foreignkey')
    op.drop_constraint('fk_invoices_billing_milestone_id', 'invoices', type_='foreignkey')

    op.drop_column('invoices', 'cancelled_by')
    op.drop_column('invoices', 'cancelled_at')
    op.drop_column('invoices', 'paid_by')
    op.drop_column('invoices', 'paid_at')
    op.drop_column('invoices', 'issued_by')
    op.drop_column('invoices', 'issued_at')
    op.drop_column('invoices', 'notes')
    op.drop_column('invoices', 'billing_milestone_id')

    op.drop_constraint('uq_invoices_invoice_number', 'invoices', type_='unique')
    op.drop_column('invoices', 'invoice_number')

    op.drop_index('ix_billing_milestones_project_id', table_name='billing_milestones')
    op.drop_constraint(
        'uq_billing_milestones_project_name', 'billing_milestones', type_='unique'
    )
    op.drop_constraint(
        'fk_billing_milestones_completed_by', 'billing_milestones', type_='foreignkey'
    )
    op.drop_table('billing_milestones')

    sa.Enum(name='billing_milestone_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='billing_type').drop(op.get_bind(), checkfirst=True)
