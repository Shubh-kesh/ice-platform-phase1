"""m14 - vendors + purchase orders

Revision ID: k4c5d6e7f8a9
Revises: j8e9f0a1b2c3
Create Date: 2026-08-14 00:00:00.000000

Adds the Phase 5 procurement foundation (M14): vendor master data and
project-scoped purchase orders with line items and a POStatus lifecycle.

Three new tables, one new enum (POStatus), no changes to existing tables:

* `vendors` — enterprise-global master data (no project_id). Unique name
  (uq_vendors_name, app 409 on duplicate), soft deactivation via
  is_active (no hard delete), indexed for the is_active filter.
* `purchase_orders` — project-scoped commitment documents. Unique
  po_number (uq_purchase_orders_po_number) auto-generated as
  PO-{project_code}-{seq:04d} under the project row lock; FK projects
  CASCADE / vendors RESTRICT (a used vendor can't be removed) / users
  SET NULL for attribution. total_amount is a denormalized running total
  recomputed in the same transaction as every line/header mutation.
  Indexes on project_id / vendor_id / status.
* `po_lines` — line items with quantity/unit/unit_price and a reused M4
  cost_code (forward hook for M15 receiving -> job-cost tagging). line_total
  is derived on read (never stored). Index on purchase_order_id.

Enum-backed columns are added via op.add_column (ALTER TABLE) after the enums
are created explicitly with checkfirst — the SQLAlchemy 2.0.35
op.create_table path re-emits a non-checkfirst CREATE TYPE and fails with
DuplicateObject (the documented M5 lesson). The cost_code enum is reused from
M4 (already exists) and is likewise added via op.add_column.

Downgrade drops po_lines -> purchase_orders -> vendors (constraints/indexes
first), then drops the POStatus enum. The shared cost_code enum is untouched.
No existing table/data is affected in either direction.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'k4c5d6e7f8a9'
down_revision = 'j8e9f0a1b2c3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade schema."""
    po_status = sa.Enum(
        'DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED', 'CANCELLED',
        name='po_status',
    )
    po_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'vendors',
        sa.Column('id', sa.UUID(), primary_key=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('contact_name', sa.String(length=255), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('phone', sa.String(length=50), nullable=True),
        sa.Column('payment_terms', sa.String(length=255), nullable=True),
        sa.Column('address', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_unique_constraint('uq_vendors_name', 'vendors', ['name'])
    op.create_index('ix_vendors_is_active', 'vendors', ['is_active'])

    op.create_table(
        'purchase_orders',
        sa.Column('id', sa.UUID(), primary_key=True),
        sa.Column('po_number', sa.String(length=40), nullable=False),
        sa.Column(
            'project_id',
            sa.UUID(),
            sa.ForeignKey('projects.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'vendor_id',
            sa.UUID(),
            sa.ForeignKey('vendors.id', ondelete='RESTRICT'),
            nullable=False,
        ),
        sa.Column('order_date', sa.Date(), nullable=False),
        sa.Column('expected_delivery', sa.Date(), nullable=True),
        sa.Column('tax_rate', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column(
            'total_amount', sa.Numeric(precision=14, scale=2), nullable=False,
            server_default=sa.text('0'),
        ),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column(
            'created_by', sa.UUID(), nullable=True
        ),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('submitted_by', sa.UUID(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_by', sa.UUID(), nullable=True),
        sa.Column('rejected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejected_by', sa.UUID(), nullable=True),
        sa.Column('rejected_reason', sa.Text(), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancelled_by', sa.UUID(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.add_column('purchase_orders', sa.Column('status', po_status, nullable=False))
    op.create_foreign_key(
        'fk_purchase_orders_created_by',
        'purchase_orders', 'users', ['created_by'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_purchase_orders_submitted_by',
        'purchase_orders', 'users', ['submitted_by'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_purchase_orders_approved_by',
        'purchase_orders', 'users', ['approved_by'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_purchase_orders_rejected_by',
        'purchase_orders', 'users', ['rejected_by'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_purchase_orders_cancelled_by',
        'purchase_orders', 'users', ['cancelled_by'], ['id'], ondelete='SET NULL',
    )
    op.create_unique_constraint(
        'uq_purchase_orders_po_number', 'purchase_orders', ['po_number']
    )
    op.create_index(
        'ix_purchase_orders_project_id', 'purchase_orders', ['project_id']
    )
    op.create_index(
        'ix_purchase_orders_vendor_id', 'purchase_orders', ['vendor_id']
    )
    op.create_index(
        'ix_purchase_orders_status', 'purchase_orders', ['status']
    )

    op.create_table(
        'po_lines',
        sa.Column('id', sa.UUID(), primary_key=True),
        sa.Column(
            'purchase_order_id',
            sa.UUID(),
            sa.ForeignKey('purchase_orders.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('description', sa.String(length=255), nullable=False),
        sa.Column('quantity', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('unit', sa.String(length=50), nullable=False),
        sa.Column('unit_price', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.add_column(
        'po_lines',
        # Reuses the M4 `cost_code` type (already created); create_type=False
        # stops ADD COLUMN from re-emitting a CREATE TYPE for an existing type.
        sa.Column('cost_code', postgresql.ENUM(name='cost_code', create_type=False), nullable=False),
    )
    op.create_index(
        'ix_po_lines_purchase_order_id', 'po_lines', ['purchase_order_id']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_po_lines_purchase_order_id', table_name='po_lines')
    op.drop_table('po_lines')

    op.drop_index('ix_purchase_orders_status', table_name='purchase_orders')
    op.drop_index('ix_purchase_orders_vendor_id', table_name='purchase_orders')
    op.drop_index('ix_purchase_orders_project_id', table_name='purchase_orders')
    op.drop_constraint(
        'uq_purchase_orders_po_number', 'purchase_orders', type_='unique'
    )
    op.drop_constraint(
        'fk_purchase_orders_cancelled_by', 'purchase_orders', type_='foreignkey'
    )
    op.drop_constraint(
        'fk_purchase_orders_rejected_by', 'purchase_orders', type_='foreignkey'
    )
    op.drop_constraint(
        'fk_purchase_orders_approved_by', 'purchase_orders', type_='foreignkey'
    )
    op.drop_constraint(
        'fk_purchase_orders_submitted_by', 'purchase_orders', type_='foreignkey'
    )
    op.drop_constraint(
        'fk_purchase_orders_created_by', 'purchase_orders', type_='foreignkey'
    )
    op.drop_column('purchase_orders', 'status')
    op.drop_table('purchase_orders')

    op.drop_index('ix_vendors_is_active', table_name='vendors')
    op.drop_constraint('uq_vendors_name', 'vendors', type_='unique')
    op.drop_table('vendors')

    sa.Enum(name='po_status').drop(op.get_bind(), checkfirst=True)
