"""m1 - index stock_movements for ledger listing

Revision ID: a4b6c8d9e2f3
Revises: 8f3a1c2d9e01
Create Date: 2026-08-09 19:30:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a4b6c8d9e2f3'
down_revision: Union[str, Sequence[str], None] = '8f3a1c2d9e01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index('ix_stock_movements_created_at', 'stock_movements', ['created_at'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_stock_movements_created_at', table_name='stock_movements')