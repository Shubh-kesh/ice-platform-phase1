"""m15 - receiving/deliveries

Revision ID: l5d6e7f8a9b0
Revises: k4c5d6e7f8a9
Create Date: 2026-08-14 00:00:00.000000

M15 delivery verification / receiving. Additive: extends the `po_status` enum
with PARTIALLY_RECEIVED / RECEIVED, adds receiving columns to existing tables,
and adds two new evidence tables (`deliveries`, `delivery_lines`). No existing
data is touched or backfilled.

* `po_status` enum: `ALTER TYPE ... ADD VALUE IF NOT EXISTS 'PARTIALLY_RECEIVED'`
  and `'RECEIVED'` — additive. Postgres forbids *using* a new enum value in the
  same transaction that adds it, and this migration never inserts/updates rows
  to the new values (pure schema change), so that constraint is satisfied.
* `po_lines` += `received_quantity` Numeric(12,2) NOT NULL DEFAULT 0
  (accumulating server-derived total across receipts) and `inventory_item_id`
  UUID NULL FK inventory_items.id ON DELETE SET NULL (the item a line feeds;
  set on first receipt, app-immutable).
* `stock_movements` += `po_line_id` UUID NULL FK po_lines.id ON DELETE SET NULL
  — provenance on the immutable ledger for RECEIVED movements.
* `job_costs` += `po_line_id` UUID NULL FK po_lines.id ON DELETE SET NULL —
  provenance for material costs released by a receipt.
* New `deliveries` (receipt/evidence header: reference, note, photo_reference,
  verified_by/at, created_by) and `delivery_lines` (per-PO-line quantity +
  snapshotted unit_price/line_total). Append-only — no update/delete endpoints.

Downgrade drops `delivery_lines` -> `deliveries` and the added columns/FKs. The
two new enum members cannot be dropped (Postgres has no ALTER TYPE DROP VALUE);
they remain present-but-unused. A full downgrade to base drops the whole
`po_status` type via the M14 downgrade, so the chain test stays replayable.
"""
import sqlalchemy as sa
from alembic import op

revision = 'l5d6e7f8a9b0'
down_revision = 'k4c5d6e7f8a9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "ALTER TYPE po_status ADD VALUE IF NOT EXISTS 'PARTIALLY_RECEIVED'"
    )
    op.execute("ALTER TYPE po_status ADD VALUE IF NOT EXISTS 'RECEIVED'")

    op.add_column(
        'po_lines',
        sa.Column(
            'received_quantity',
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default=sa.text('0'),
        ),
    )
    op.add_column(
        'po_lines',
        sa.Column('inventory_item_id', sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        'fk_po_lines_inventory_item_id',
        'po_lines',
        'inventory_items',
        ['inventory_item_id'],
        ['id'],
        ondelete='SET NULL',
    )

    op.add_column(
        'stock_movements',
        sa.Column('po_line_id', sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        'fk_stock_movements_po_line_id',
        'stock_movements',
        'po_lines',
        ['po_line_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_index(
        'ix_stock_movements_po_line_id', 'stock_movements', ['po_line_id']
    )

    op.add_column(
        'job_costs',
        sa.Column('po_line_id', sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        'fk_job_costs_po_line_id',
        'job_costs',
        'po_lines',
        ['po_line_id'],
        ['id'],
        ondelete='SET NULL',
    )

    op.create_table(
        'deliveries',
        sa.Column('id', sa.UUID(), primary_key=True),
        sa.Column(
            'project_id',
            sa.UUID(),
            sa.ForeignKey('projects.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'purchase_order_id',
            sa.UUID(),
            sa.ForeignKey('purchase_orders.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('reference', sa.String(length=100), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('photo_reference', sa.String(length=500), nullable=True),
        sa.Column('verified_by', sa.UUID(), nullable=True),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_foreign_key(
        'fk_deliveries_verified_by',
        'deliveries', 'users', ['verified_by'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_deliveries_created_by',
        'deliveries', 'users', ['created_by'], ['id'], ondelete='SET NULL',
    )
    op.create_index(
        'ix_deliveries_purchase_order_id', 'deliveries', ['purchase_order_id']
    )
    op.create_index(
        'ix_deliveries_project_id', 'deliveries', ['project_id']
    )
    op.create_index(
        'ix_deliveries_verified_at', 'deliveries', ['verified_at']
    )

    op.create_table(
        'delivery_lines',
        sa.Column('id', sa.UUID(), primary_key=True),
        sa.Column(
            'delivery_id',
            sa.UUID(),
            sa.ForeignKey('deliveries.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'po_line_id',
            sa.UUID(),
            sa.ForeignKey('po_lines.id', ondelete='RESTRICT'),
            nullable=False,
        ),
        sa.Column(
            'inventory_item_id',
            sa.UUID(),
            sa.ForeignKey('inventory_items.id', ondelete='RESTRICT'),
            nullable=False,
        ),
        sa.Column('quantity_received', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('unit_price', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('line_total', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        'ix_delivery_lines_delivery_id', 'delivery_lines', ['delivery_id']
    )
    op.create_index(
        'ix_delivery_lines_po_line_id', 'delivery_lines', ['po_line_id']
    )
    op.create_index(
        'ix_delivery_lines_inventory_item_id', 'delivery_lines', ['inventory_item_id']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_delivery_lines_inventory_item_id', table_name='delivery_lines')
    op.drop_index('ix_delivery_lines_po_line_id', table_name='delivery_lines')
    op.drop_index('ix_delivery_lines_delivery_id', table_name='delivery_lines')
    op.drop_table('delivery_lines')

    op.drop_index('ix_deliveries_verified_at', table_name='deliveries')
    op.drop_index('ix_deliveries_project_id', table_name='deliveries')
    op.drop_index('ix_deliveries_purchase_order_id', table_name='deliveries')
    op.drop_constraint(
        'fk_deliveries_created_by', 'deliveries', type_='foreignkey'
    )
    op.drop_constraint(
        'fk_deliveries_verified_by', 'deliveries', type_='foreignkey'
    )
    op.drop_table('deliveries')

    op.drop_index('ix_stock_movements_po_line_id', table_name='stock_movements')
    op.drop_constraint(
        'fk_stock_movements_po_line_id', 'stock_movements', type_='foreignkey'
    )
    op.drop_column('stock_movements', 'po_line_id')

    op.drop_constraint('fk_job_costs_po_line_id', 'job_costs', type_='foreignkey')
    op.drop_column('job_costs', 'po_line_id')

    op.drop_constraint(
        'fk_po_lines_inventory_item_id', 'po_lines', type_='foreignkey'
    )
    op.drop_column('po_lines', 'inventory_item_id')
    op.drop_column('po_lines', 'received_quantity')

    # po_status enum values (PARTIALLY_RECEIVED/RECEIVED) cannot be dropped;
    # they remain present-but-unused. A full downgrade to base drops the whole
    # enum via the M14 downgrade, keeping the chain test replayable.
