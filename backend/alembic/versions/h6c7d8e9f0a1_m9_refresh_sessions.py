"""m9 - refresh-token security: server-side refresh sessions

Revision ID: h6c7d8e9f0a1
Revises: g5b6c7d8e9f0
Create Date: 2026-08-12 00:00:00.000000

Adds `refresh_sessions`, the server-side half of M9 token security. Every
refresh token issued is an opaque random secret; only its SHA-256 digest is
stored (`token_hash`), so a database leak never exposes a usable token. Rows
are single-use: rotation revokes the presented row and inserts a child in the
same family; reuse of a dead token triggers family-wide revocation (theft
signal); deactivation revokes every outstanding session for the user.

Constraints (directly verified in PostgreSQL):
  * unique index on token_hash  — a token can exist at most once (single-use)
  * FK user_id -> users.id (CASCADE)       — sessions die with the account
  * FK parent_id -> refresh_sessions.id (SET NULL) — rotation chain
  * ix_refresh_sessions_family     — backs family revocation
  * ix_refresh_sessions_user_revoked — lists a user's live sessions
  * ix_refresh_sessions_expires    — opportunistic cleanup

No enums are introduced; `revoked_reason` is a plain VARCHAR. No
Google-specific columns — the schema stays M11-compatible.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'h6c7d8e9f0a1'
down_revision = 'g5b6c7d8e9f0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'refresh_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'user_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('token_hash', sa.String(length=64), unique=True, nullable=False),
        sa.Column('family_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            'parent_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('refresh_sessions.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column(
            'issued_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_reason', sa.String(length=32), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        'ix_refresh_sessions_user_revoked', 'refresh_sessions', ['user_id', 'revoked_at']
    )
    op.create_index('ix_refresh_sessions_family', 'refresh_sessions', ['family_id'])
    op.create_index('ix_refresh_sessions_expires', 'refresh_sessions', ['expires_at'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_refresh_sessions_expires', table_name='refresh_sessions')
    op.drop_index('ix_refresh_sessions_family', table_name='refresh_sessions')
    op.drop_index('ix_refresh_sessions_user_revoked', table_name='refresh_sessions')
    op.drop_table('refresh_sessions')
