"""
M5 — migration-chain integrity test.

Runs the real Alembic migration chain against a scratch database:
upgrade head -> downgrade base -> upgrade head. This proves the full chain
(through the M9 refresh_sessions migration) is:
  * reversible (downgrade drops every migration object cleanly), and
  * replayable (the chain reaches the same head twice).

Runs Alembic in a subprocess with POSTGRES_DB pointed at a throwaway database,
so the running app's settings (and the active test session) are untouched.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.conftest import ADMIN_DATABASE_URL

MIGRATION_DB_NAME = "ice_migration_test_db"
HEAD_REVISION = "l5d6e7f8a9b0"
BACKEND_DIR = Path(__file__).resolve().parent.parent


def _migration_env() -> dict:
    env = dict(os.environ)
    # The alembic env.py derives its sync URL from app settings, which read
    # these vars. Point only the database name at the scratch DB.
    env["POSTGRES_DB"] = MIGRATION_DB_NAME
    return env


def _alembic(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=cwd,
        env=_migration_env(),
        capture_output=True,
        text=True,
    )


async def _ensure_migration_database() -> None:
    engine = create_async_engine(ADMIN_DATABASE_URL, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            exists = await conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": MIGRATION_DB_NAME},
            )
            if exists.scalar_one_or_none() is None:
                await conn.execute(text(f'CREATE DATABASE "{MIGRATION_DB_NAME}"'))
    finally:
        await engine.dispose()


async def _drop_migration_database() -> None:
    engine = create_async_engine(ADMIN_DATABASE_URL, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{MIGRATION_DB_NAME}"'))
    finally:
        await engine.dispose()


async def _table_exists(table: str) -> bool:
    engine = create_async_engine(
        ADMIN_DATABASE_URL.replace("/postgres", f"/{MIGRATION_DB_NAME}")
    )
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = :t"
                ),
                {"t": table},
            )
            return result.scalar_one_or_none() is not None
    finally:
        await engine.dispose()


async def _column_exists(table: str, column: str) -> bool:
    """M11/M15 — confirm a specific table column is present after upgrade."""
    engine = create_async_engine(
        ADMIN_DATABASE_URL.replace("/postgres", f"/{MIGRATION_DB_NAME}")
    )
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
                ),
                {"t": table, "c": column},
            )
            return result.scalar_one_or_none() is not None
    finally:
        await engine.dispose()


async def _enum_has_value(enum_name: str, value: str) -> bool:
    """M15 — confirm a native enum type contains a specific label."""
    engine = create_async_engine(
        ADMIN_DATABASE_URL.replace("/postgres", f"/{MIGRATION_DB_NAME}")
    )
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT 1 FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                    "WHERE t.typname = :name AND e.enumlabel = :value"
                ),
                {"name": enum_name, "value": value},
            )
            return result.scalar_one_or_none() is not None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_migration_chain_upgrade_downgrade_replayable():
    await _drop_migration_database()  # idempotent cleanup from a failed run
    await _ensure_migration_database()

    try:
        up = _alembic(["upgrade", "head"], cwd=BACKEND_DIR)
        assert up.returncode == 0, up.stderr or up.stdout
        current = _alembic(["current"], cwd=BACKEND_DIR)
        assert HEAD_REVISION in current.stdout, current.stdout

        for table in (
            "billing_milestones",
            "invoices",
            "refresh_sessions",
            "notifications",
            "vendors",
            "purchase_orders",
            "po_lines",
            "deliveries",
            "delivery_lines",
        ):
            assert await _table_exists(table), f"{table} missing after upgrade head"
        for table, column in (
            ("users", "google_sub"),
            ("users", "google_email"),
            ("po_lines", "received_quantity"),
            ("po_lines", "inventory_item_id"),
            ("stock_movements", "po_line_id"),
            ("job_costs", "po_line_id"),
        ):
            assert await _column_exists(table, column), f"{table}.{column} missing after upgrade head"
        for value in ("PARTIALLY_RECEIVED", "RECEIVED"):
            assert await _enum_has_value("po_status", value), f"po_status.{value} missing after upgrade head"

        down = _alembic(["downgrade", "base"], cwd=BACKEND_DIR)
        assert down.returncode == 0, down.stderr or down.stdout

        for table in (
            "billing_milestones",
            "invoices",
            "refresh_sessions",
            "notifications",
            "vendors",
            "purchase_orders",
            "po_lines",
            "deliveries",
            "delivery_lines",
        ):
            assert not await _table_exists(table), f"{table} not dropped on downgrade"
        for table, column in (
            ("users", "google_sub"),
            ("users", "google_email"),
            ("po_lines", "received_quantity"),
            ("po_lines", "inventory_item_id"),
            ("stock_movements", "po_line_id"),
            ("job_costs", "po_line_id"),
        ):
            assert not await _column_exists(table, column), f"{table}.{column} not dropped on downgrade"

        replay = _alembic(["upgrade", "head"], cwd=BACKEND_DIR)
        assert replay.returncode == 0, replay.stderr or replay.stdout

        current_again = _alembic(["current"], cwd=BACKEND_DIR)
        assert HEAD_REVISION in current_again.stdout
    finally:
        await _drop_migration_database()
