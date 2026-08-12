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
HEAD_REVISION = "i7d8e9f0a1b2"
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


async def _column_exists(column: str) -> bool:
    """M11 — confirm `users.google_sub`/`google_email` are present after upgrade."""
    engine = create_async_engine(
        ADMIN_DATABASE_URL.replace("/postgres", f"/{MIGRATION_DB_NAME}")
    )
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'users' AND column_name = :c"
                ),
                {"c": column},
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

        for table in ("billing_milestones", "invoices", "refresh_sessions"):
            assert await _table_exists(table), f"{table} missing after upgrade head"
        for column in ("google_sub", "google_email"):
            assert await _column_exists(column), f"users.{column} missing after upgrade head"

        down = _alembic(["downgrade", "base"], cwd=BACKEND_DIR)
        assert down.returncode == 0, down.stderr or down.stdout

        for table in ("billing_milestones", "invoices", "refresh_sessions"):
            assert not await _table_exists(table), f"{table} not dropped on downgrade"
        for column in ("google_sub", "google_email"):
            assert not await _column_exists(column), f"users.{column} not dropped on downgrade"

        replay = _alembic(["upgrade", "head"], cwd=BACKEND_DIR)
        assert replay.returncode == 0, replay.stderr or replay.stdout

        current_again = _alembic(["current"], cwd=BACKEND_DIR)
        assert HEAD_REVISION in current_again.stdout
    finally:
        await _drop_migration_database()
