"""m3 - health overrides: audited manual health verdicts

Revision ID: e8f2a3c5b7e4
Revises: d7e9f1a2b3c4
Create Date: 2026-08-11 09:00:00.000000

Adds the health_overrides table backing M3's audited manual override of a
computed health verdict. Computed health itself is derived on read (no new
columns); the legacy timeline_health/budget_health/safety_health columns are
deprecated, not dropped.

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'e8f2a3c5b7e4'
down_revision = 'd7e9f1a2b3c4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade schema."""
    # The manual health verdict columns (timeline_health/budget_health/
    # safety_health) were created with enum types that only know
    # GREEN/AMBER/RED. M3 adds NOT_RATED to the Python HealthStatus enum, but
    # those deprecated columns never store it, so their DB enum types stay as-is.

    # Widen audit_logs.action: M3's health_override_revoked (26 chars) exceeds
    # the legacy String(20) that only anticipated create/update/delete.
    op.alter_column(
        'audit_logs', 'action',
        existing_type=sa.String(length=20),
        type_=sa.String(length=100),
        existing_nullable=False,
    )

    health_override_target = sa.Enum(
        'OVERALL', 'TIMELINE', 'BUDGET', 'SAFETY', name='health_override_target'
    )
    health_override_target.create(op.get_bind(), checkfirst=True)

    health_override_value = sa.Enum(
        'GREEN', 'AMBER', 'RED', name='health_override_value'
    )
    health_override_value.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'health_overrides',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'project_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('projects.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('set_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_by', postgresql.UUID(as_uuid=True), nullable=True),
    )

    # The enum-backed columns are added via ALTER so op.create_table never fires
    # its unconditional CREATE TYPE for them (SQLAlchemy 2.0.35 'op.create_table'
    # path: _on_table_create ignores create_type=False for a non-metadata enum and
    # emits a second, non-checkfirst CREATE TYPE -> DuplicateObject).
    op.add_column(
        'health_overrides',
        sa.Column('applied_to', health_override_target, nullable=False),
    )
    op.add_column(
        'health_overrides',
        sa.Column('value', health_override_value, nullable=False),
    )
    op.create_foreign_key(
        'fk_health_overrides_set_by',
        'health_overrides', 'users', ['set_by'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_health_overrides_revoked_by',
        'health_overrides', 'users', ['revoked_by'], ['id'], ondelete='SET NULL',
    )

    # Single-active-per-(project, applied_to) guarantee. A row leaves the active
    # set on revoke, so history for the same target can grow without violating
    # uniqueness. Expiry is handled in the application layer (Postgres forbids
    # `now()` in an index predicate).
    op.create_index(
        'uq_health_overrides_active_per_target',
        'health_overrides',
        ['project_id', 'applied_to'],
        unique=True,
        postgresql_where=sa.text('revoked_at IS NULL'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_health_overrides_active_per_target', table_name='health_overrides')
    op.drop_constraint('fk_health_overrides_revoked_by', 'health_overrides', type_='foreignkey')
    op.drop_constraint('fk_health_overrides_set_by', 'health_overrides', type_='foreignkey')
    op.drop_table('health_overrides')

    sa.Enum(name='health_override_value').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='health_override_target').drop(op.get_bind(), checkfirst=True)

    op.alter_column(
        'audit_logs', 'action',
        existing_type=sa.String(length=100),
        type_=sa.String(length=20),
        existing_nullable=False,
    )