"""m10 - project lifecycle: code + status enum + audit columns

Revision ID: d7e9f1a2b3c4
Revises: c6d8e0f2a415
Create Date: 2026-08-10 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd7e9f1a2b3c4'
down_revision: Union[str, Sequence[str], None] = 'c6d8e0f2a415'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Extend the project_status enum with the lifecycle DRAFT/ARCHIVED states.
    # Values are stored by member name (SQLAlchemy Enum default), matching the
    # existing PLANNING/ACTIVE/ON_HOLD/COMPLETED member names.
    op.execute("ALTER TYPE project_status ADD VALUE IF NOT EXISTS 'DRAFT'")
    op.execute("ALTER TYPE project_status ADD VALUE IF NOT EXISTS 'ARCHIVED'")

    # project_code — unique human-readable identifier. Add nullable first,
    # backfill legacy/demo rows, then enforce NOT NULL + uniqueness.
    op.add_column('projects', sa.Column('project_code', sa.String(length=20), nullable=True))
    op.execute(
        """
        UPDATE projects AS p
        SET project_code = 'PRJ-' || EXTRACT(YEAR FROM p.created_at)::text || '-' ||
                           LPAD(s.seq::text, 4, '0')
        FROM (
            SELECT id, ROW_NUMBER() OVER (ORDER BY created_at, id) AS seq
            FROM projects
        ) s
        WHERE p.id = s.id
        """
    )
    op.alter_column('projects', 'project_code', nullable=False)
    op.create_unique_constraint('uq_projects_project_code', 'projects', ['project_code'])

    # Lifecycle attribution columns (who/what/when) — all nullable on legacy rows.
    op.add_column('projects', sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('projects', sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('projects', sa.Column('completed_by', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('projects', sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('projects', sa.Column('archived_by', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('projects', sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('projects', sa.Column('restored_by', postgresql.UUID(as_uuid=True), nullable=True))

    op.create_foreign_key('fk_projects_created_by', 'projects', 'users', ['created_by'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_projects_completed_by', 'projects', 'users', ['completed_by'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_projects_archived_by', 'projects', 'users', ['archived_by'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_projects_restored_by', 'projects', 'users', ['restored_by'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_projects_restored_by', 'projects', type_='foreignkey')
    op.drop_constraint('fk_projects_archived_by', 'projects', type_='foreignkey')
    op.drop_constraint('fk_projects_completed_by', 'projects', type_='foreignkey')
    op.drop_constraint('fk_projects_created_by', 'projects', type_='foreignkey')

    op.drop_column('projects', 'restored_by')
    op.drop_column('projects', 'restored_at')
    op.drop_column('projects', 'archived_by')
    op.drop_column('projects', 'archived_at')
    op.drop_column('projects', 'completed_by')
    op.drop_column('projects', 'completed_at')
    op.drop_column('projects', 'created_by')

    op.drop_constraint('uq_projects_project_code', 'projects', type_='unique')
    op.drop_column('projects', 'project_code')