"""m4 - job costs: cost_code enum + budget index

Revision ID: c6d8e0f2a415
Revises: b5c7d9e1f203
Create Date: 2026-08-10 09:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c6d8e0f2a415'
down_revision: Union[str, Sequence[str], None] = 'b5c7d9e1f203'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COST_CODES = [
    'FOUNDATION', 'STRUCTURE', 'MASONRY', 'ROOFING', 'ELECTRICAL',
    'PLUMBING', 'HVAC', 'FINISHING', 'LANDSCAPING', 'LABOR', 'MATERIAL',
    'EQUIPMENT', 'OTHER',
]


def upgrade() -> None:
    """Upgrade schema."""
    # Create the enum type before referencing it in the column definition.
    cost_code = postgresql.ENUM(*COST_CODES, name='cost_code')
    cost_code.create(op.get_bind(), checkfirst=True)

    # job_costs.category (free-text, unused) is replaced by a typed cost_code
    # enum so the finance roll-up works off a clean dimension.
    op.add_column('job_costs', sa.Column('cost_code', cost_code, nullable=True))

    # Backfill any legacy rows as 'other' (no endpoint ever wrote to this
    # table, so this is defensive only), then drop the free-text column.
    op.execute("UPDATE job_costs SET cost_code = 'OTHER'")
    op.alter_column('job_costs', 'cost_code', nullable=False)
    op.drop_column('job_costs', 'category')

    # Composite index for the standard "project + date" finance listing.
    op.create_index(
        'ix_job_costs_project_incurred', 'job_costs', ['project_id', 'incurred_on']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_job_costs_project_incurred', table_name='job_costs')
    op.add_column(
        'job_costs',
        sa.Column('category', sa.String(length=100), nullable=False, server_default='other'),
    )
    op.drop_column('job_costs', 'cost_code')
    postgresql.ENUM(name='cost_code').drop(op.get_bind(), checkfirst=True)