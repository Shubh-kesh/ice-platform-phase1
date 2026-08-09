"""m2 - unique project assignments

Revision ID: b5c7d9e1f203
Revises: a4b6c8d9e2f3
Create Date: 2026-08-09 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b5c7d9e1f203'
down_revision: Union[str, Sequence[str], None] = 'a4b6c8d9e2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Defensive de-dupe before the constraint can be applied: if a legacy
    # (project_id, user_id) got assigned twice, keep only the earliest row.
    op.get_bind().execute(
        sa.text(
            """
            DELETE FROM project_assignments pa
            USING project_assignments pa2
            WHERE pa.id > pa2.id
              AND pa.project_id = pa2.project_id
              AND pa.user_id = pa2.user_id
            """
        )
    )
    op.create_unique_constraint(
        'uq_project_assignments_project_user', 'project_assignments', ['project_id', 'user_id']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('uq_project_assignments_project_user', 'project_assignments', type_='unique')