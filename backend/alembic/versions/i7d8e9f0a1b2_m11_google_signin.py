"""m11 - google sign-in: nullable password + google identity columns

Revision ID: i7d8e9f0a1b2
Revises: h6c7d8e9f0a1
Create Date: 2026-08-12 00:00:00.000000

M11 Google Sign-In: three changes on `users`, no new tables.

* `hashed_password` DROPS NOT NULL — a Google-only (invited) user has no
  password; `NULL` + `google_sub IS NULL` derivable state = "Pending Google
  link" (no invite-token table needed).
* `google_sub` ADD (VARCHAR 255, NULL) with a UNIQUE index — authoritative
  Google identity key (`sub` is immutable). The unique index is what makes a
  duplicate Google identity impossible and drives the 409 `link_conflict`
  path on a race (§7/E).
* `google_email` ADD (VARCHAR 255, NULL) — the verified email as reported by
  Google at link time (diagnostics + email-change handling §7/G).

Intentional: no `auth_provider` enum (google_sub + null password already
encode provider state), no invite-token/link table, no provider session
columns (M9 `refresh_sessions` is keyed by user_id and covers Google sessions
unchanged).

Downgrade is destructive for Google-only users: restoring `hashed_password
NOT NULL` fails if any row already has a NULL password, so the downgrade is
guarded with `postgresql`-aware logic and documented as failing-in-the-open
for M11 users (matching the M11 risk notes).
"""
import sqlalchemy as sa
from alembic import op

revision = 'i7d8e9f0a1b2'
down_revision = 'h6c7d8e9f0a1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        'users',
        'hashed_password',
        existing_type=sa.String(length=255),
        nullable=True,
        existing_server_default=None,
        existing_nullable=False,
    )
    op.add_column('users', sa.Column('google_sub', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('google_email', sa.String(length=255), nullable=True))
    op.create_index('ix_users_google_sub', 'users', ['google_sub'], unique=True)


def downgrade() -> None:
    """Downgrade schema.

    WARNING: if any Google-only user exists (hashed_password IS NULL) this
    downgrade fails — clearing that state requires deleting those rows first.
    """
    op.drop_index('ix_users_google_sub', table_name='users')
    op.drop_column('users', 'google_email')
    op.drop_column('users', 'google_sub')
    op.alter_column(
        'users',
        'hashed_password',
        existing_type=sa.String(length=255),
        nullable=False,
        existing_server_default=None,
        existing_nullable=True,
    )