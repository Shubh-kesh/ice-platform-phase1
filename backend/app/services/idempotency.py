"""
M8 — idempotency-key infrastructure.

Server-side idempotency for POST mutations, built around the existing
inline-handler + single-session-per-request architecture:

* The `get_idempotency_guard` dependency (in app/api/deps.py) claims the
  `Idempotency-Key` header and hands the endpoint an `IdempotencyGuard`.
* The claim row is inserted into the SAME transaction the handler commits, so
  the idempotency record and the business mutation are atomic: a failed handler
  rolls the claim back with it (the key stays free for a safe retry), and a
  successful handler finalizes the claim to `completed` with the exact response
  before committing.
* The DB unique index (actor_id, operation, idempotency_key) serializes
  concurrent same-key requests: the second INSERT blocks until the first
  transaction commits or aborts, then reads the winner's committed record and
  replays it — exactly one business operation executes per key.

Fingerprints canonicalize the request (method + route template + resolved path
params + query + sorted JSON body) so a key reused with a *different* request is
rejected with a 409 instead of silently replaying the wrong result.
"""
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.idempotency import IdempotencyRecord
from app.models.user import User

IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"
IDEMPOTENCY_TTL = timedelta(hours=24)
IDEMPOTENCY_KEY_MIN_LENGTH = 8
IDEMPOTENCY_KEY_MAX_LENGTH = 128

_STATUS_IN_PROGRESS = "in_progress"
_STATUS_COMPLETED = "completed"


class IdempotencyGuard:
    """Per-request handle for an idempotent mutation.

    `enabled=False` (no header) makes every method a no-op so all call sites
    share one type. `replay` is set when this request is a retry of an
    already-completed claim: the endpoint must return it verbatim instead of
    executing any business logic.
    """

    def __init__(
        self,
        *,
        enabled: bool,
        record: IdempotencyRecord | None = None,
        replay: JSONResponse | None = None,
    ) -> None:
        self.enabled = enabled
        self.record = record
        self.replay = replay

    async def finish(
        self,
        db: AsyncSession,
        *,
        status_code: int,
        response_model: Any,
        obj: Any,
    ) -> None:
        """Finalize the claim with the response; the caller commits.

        Serializes `obj` through the endpoint's response schema so the stored
        body is what a normal (non-replayed) response would return. Must run
        before the handler's `db.commit()` so claim + mutation + audit land
        atomically — a mid-transaction error still rolls everything back and
        leaves the key free for a safe retry.
        """
        if not self.enabled or self.record is None:
            return
        await db.flush()
        await db.refresh(obj)  # populate server defaults (created_at, ...) pre-serialization
        body = response_model.model_validate(obj).model_dump(mode="json")
        self.record.status = _STATUS_COMPLETED
        self.record.response_status = status_code
        self.record.response_body = json.dumps(body, sort_keys=True, separators=(",", ":"))
        self.record.completed_at = datetime.now(timezone.utc)

    async def reclaim(self, db: AsyncSession) -> None:
        """Re-claim after the caller rolled the transaction back.

        create_project regenerates its project code inside an IntegrityError
        retry loop; each rollback also rolls back the claim, so a fresh claim
        must be re-added before the retry commits.
        """
        if not self.enabled or self.record is None:
            return
        self.record = _new_claim(
            actor_id=self.record.actor_id,
            idempotency_key=self.record.idempotency_key,
            operation=self.record.operation,
            fingerprint=self.record.request_fingerprint,
        )
        db.add(self.record)


def _new_claim(
    *,
    actor_id: uuid.UUID,
    idempotency_key: str,
    operation: str,
    fingerprint: str,
) -> IdempotencyRecord:
    return IdempotencyRecord(
        actor_id=actor_id,
        idempotency_key=idempotency_key,
        operation=operation,
        request_fingerprint=fingerprint,
        status=_STATUS_IN_PROGRESS,
        expires_at=datetime.now(timezone.utc) + IDEMPOTENCY_TTL,
    )


def _operation_route(request: Request) -> str:
    """Stable route template, e.g. /projects/{project_id}/job-costs.

    Uses the matched route template rather than the concrete URL so the same
    path shape maps to the same operation string regardless of the params.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if path else request.url.path


async def _fingerprint(request: Request) -> str:
    """Canonical hash of the request: method + route + params + query + body.

    The body is parsed and re-dumped with sorted keys, so whitespace, key order
    and trailing-zero amounts (100.1 vs 100.10) hash identically — semantic
    equality, not byte equality.
    """
    raw = await request.body()
    try:
        body = json.loads(raw) if raw else None
    except (ValueError, UnicodeDecodeError):
        body = raw.decode("utf-8", "replace")
    source = json.dumps(
        {
            "method": request.method,
            "route": _operation_route(request),
            "path_params": {k: str(v) for k, v in sorted(request.path_params.items())},
            "query": sorted((k, v) for k, v in request.query_params.multi_items()),
            "body": body,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(source.encode()).hexdigest()


async def claim_idempotency(
    request: Request, db: AsyncSession, user: User, key: str
) -> IdempotencyGuard:
    """Claim `key` for this request, or resolve the conflict if already used.

    Ordering matters for correctness and for the transaction lifecycle:

    1. Look up an existing claim for (actor, operation, key) FIRST. A retry or
       a conflicting reuse is resolved here — no insert, no rollback. The
       insert path (step 2) is only reached when no claim exists yet, so the
       common retry case never leaves the session in a rolled-back state.
    2. Insert the claim. The unique index doubles as the concurrency gate: if a
       concurrent request with the same key already has a claim in flight, this
       INSERT blocks until that transaction ends, then either replays its
       committed response or, if it aborted, proceeds to execute here.
    """
    operation = _operation_route(request)
    fingerprint = await _fingerprint(request)

    # Snapshot the actor id up-front: the loser of a concurrent same-key race
    # rolls back below, which expires the session's loaded objects — re-reading
    # user.id there would lazy-load synchronously and raise MissingGreenlet.
    actor_id = user.id

    existing = await _find_record(db, actor_id, operation, key)
    if existing is not None:
        return _conflict_or_replay(existing, fingerprint)

    claim = _new_claim(
        actor_id=actor_id, idempotency_key=key, operation=operation, fingerprint=fingerprint
    )
    db.add(claim)
    try:
        await db.flush()
    except IntegrityError:
        # Lost a race to a concurrent same-key request that committed between
        # our SELECT and INSERT. Its claim is now committed; roll back the
        # failed insert and resolve against the winner.
        await db.rollback()
        winner = await _find_record(db, actor_id, operation, key)
        if winner is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Idempotency-Key conflict; retry with a new key",
            )
        return _conflict_or_replay(winner, fingerprint)
    return IdempotencyGuard(enabled=True, record=claim)


async def _find_record(
    db: AsyncSession, actor_id: uuid.UUID, operation: str, key: str
) -> IdempotencyRecord | None:
    result = await db.execute(
        select(IdempotencyRecord).where(
            IdempotencyRecord.actor_id == actor_id,
            IdempotencyRecord.operation == operation,
            IdempotencyRecord.idempotency_key == key,
        )
    )
    return result.scalar_one_or_none()


def _conflict_or_replay(existing: IdempotencyRecord, fingerprint: str) -> IdempotencyGuard:
    now = datetime.now(timezone.utc)

    if existing.status != _STATUS_COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A request with this Idempotency-Key is already being processed",
        )
    if existing.request_fingerprint != fingerprint:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency-Key was already used for a different request",
        )
    if existing.expires_at is not None and existing.expires_at <= now:
        # Safer than re-executing: an expired retry of a request that actually
        # succeeded would otherwise duplicate the record. Force a new key.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency-Key has expired; issue a new key for a new request",
        )

    return IdempotencyGuard(
        enabled=True,
        replay=JSONResponse(
            status_code=existing.response_status or status.HTTP_200_OK,
            content=json.loads(existing.response_body) if existing.response_body else None,
        ),
    )
