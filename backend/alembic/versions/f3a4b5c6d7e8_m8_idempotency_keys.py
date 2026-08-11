"""m8 - idempotency keys: retry-safe POST claim ledger

Revision ID: f3a4b5c6d7e8
Revises: e8f2a3c5b7e4
Create Date: 2026-08-11 12:00:00.000000

Adds idempotency_records, the server-side claim ledger backing M8. A request
carrying an `Idempotency-Key` header inserts a claim row in the same
transaction as the mutation it protects; the unique index on
(actor_id, operation, idempotency_key) serializes concurrent same-key requests
(Postgres blocks the second INSERT until the first transaction ends) and turns
a retry into a response replay instead of a re-execution. Completed claims
snapshot the response body for that replay; expired claims are rejected with a
409 so a stale retry can never silently duplicate a record.

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'f3a4b5c6d7e8'
down_revision = 'e8f2a3c5b7e4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'idempotency_records',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'actor_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('idempotency_key', sa.String(length=128), nullable=False),
        sa.Column('operation', sa.String(length=255), nullable=False),
        sa.Column('request_fingerprint', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('response_status', sa.Integer(), nullable=True),
        sa.Column('response_body', sa.Text(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    )
    # Enforcement point: only one claim per (actor, operation, key). In-flight
    # INSERTs from concurrent same-key requests block on this index until the
    # winner's transaction commits or aborts.
    op.create_unique_constraint(
        'uq_idempotency_actor_operation_key',
        'idempotency_records',
        ['actor_id', 'operation', 'idempotency_key'],
    )
    op.create_index('ix_idempotency_created_at', 'idempotency_records', ['created_at'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_idempotency_created_at', table_name='idempotency_records')
    op.drop_constraint(
        'uq_idempotency_actor_operation_key', 'idempotency_records', type_='unique'
    )
    op.drop_table('idempotency_records')
