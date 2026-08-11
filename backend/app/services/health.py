"""
Deterministic project health computation (Phase 3, M3).

Health is derived on read from source-of-truth rows — no denormalized health
columns, no randomness, no ML. Identical committed data + identical `today` +
identical active overrides => identical verdict. Routes own auth/audit; this
module owns the thresholds, the ordinal wording, and the batch context load.

Dimension vocabulary mirrors the plan:
    rated   -- enough trustworthy data exists to claim a color
    value   -- GREEN/AMBER/RED, or NOT_RATED when not rated
    reasons -- human-readable lines explaining the verdict
"""
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finance import JobCost
from app.models.health import HealthOverride, HealthOverrideTarget
from app.models.project import HealthStatus, Project, ProjectStatus
from app.models.task import Task, TaskStatus

DIMENSIONS = ("timeline", "budget", "safety")

# --- Threshold constants (single source, unit-tested — see plan §4) --------
SPI_GREEN = 0.95   # progress vs elapsed rate above which the schedule is on track
SPI_AMBER = 0.85   # below SPI_GREEN but at/above this => at-risk
BUDGET_GREEN_SLIP = "0.05"  # consumed may lead progress by up to this => GREEN
BUDGET_AMBER_SLIP = "0.15"  # ... and at most this => AMBER, above => RED
ZERO_SPEND_PROGRESS = "0.15"  # zero-ledger spend tolerated up to this progress
EARLY_BAND = 0.05     # <5% schedule elapsed: too early to rate anything
NEAR_COMPLETION = "0.95"  # >=95% complete: small overruns are demed normal
OVERDUE_AMBER_FRACTION = 0.20  # >20% tasks overdue downgrades at most to AMBER
OVERDUE_RED_FRACTION = 0.40    # >40% tasks overdue downgrades to RED

_RANK = {
    HealthStatus.GREEN: 0,
    HealthStatus.AMBER: 1,
    HealthStatus.RED: 2,
    HealthStatus.NOT_RATED: 3,
}

ARCHIVED_REASON = "Archived projects do not compute new health."


@dataclass
class HealthRating:
    """One dimension's computed verdict + its human-readable explanation."""
    value: HealthStatus
    rated: bool
    reasons: list[str] = field(default_factory=list)


@dataclass
class OverallRating:
    """Worst-of-rated across the already-rated dimensions."""
    value: HealthStatus
    rated: bool
    reasons: list[str] = field(default_factory=list)
    basis: list[str] = field(default_factory=list)


@dataclass
class HealthContext:
    """Everything one project's read needs, loaded in ~3 batched queries."""
    tasks: list[Task] = field(default_factory=list)
    spent_ledger: Decimal = Decimal("0")
    overrides: list[HealthOverride] = field(default_factory=list)


@dataclass
class ProjectHealthState:
    """Computed + effective health for one project (services-layer DTO)."""
    project: Project
    frozen: bool
    timeline: HealthRating
    budget: HealthRating
    safety: HealthRating
    effective_timeline: HealthStatus
    effective_budget: HealthStatus
    effective_safety: HealthStatus
    overall: OverallRating
    effective_overall: HealthStatus
    active_overrides: list[HealthOverride]


def _unrated(reason: str) -> HealthRating:
    return HealthRating(value=HealthStatus.NOT_RATED, rated=False, reasons=[reason])


def _lifecycle_reason(project: Project) -> HealthRating | None:
    """DRAFT/PLANNING/ON_HOLD never compute; ARCHIVED is handled by the caller."""
    if project.status in (ProjectStatus.DRAFT, ProjectStatus.PLANNING):
        return _unrated("Project is not yet in execution.")
    if project.status == ProjectStatus.ON_HOLD:
        return _unrated("Project is on hold.")
    return None


def rate_timeline(project: Project, tasks: list[Task], today: date) -> HealthRating:
    """Schedule-performance-index (SPI) rating: progress vs schedule elapsed.

    Only ever *downgrades* from the SPI verdict when a large share of tasks is
    overdue; task data can never upgrade a verdict. Dependencies are ignored
    (they are decorative in the current schema — critical path is a v2 concern).
    """
    lifecycle = _lifecycle_reason(project)
    if lifecycle is not None:
        return lifecycle

    duration = (project.target_end_date - project.start_date).days
    if duration <= 0:
        return _unrated("Timeline cannot be rated: the schedule spans zero or negative days.")

    raw_elapsed = (today - project.start_date).days
    elapsed = 0.0 if raw_elapsed < 0 else min(raw_elapsed / duration, 1.0)
    progress = project.percent_complete / 100.0

    if progress == 0 and not tasks and elapsed < EARLY_BAND:
        return _unrated("No progress or task data captured yet — project has not started.")
    if elapsed < EARLY_BAND and progress < 1.0:
        return HealthRating(
            value=HealthStatus.GREEN,
            rated=True,
            reasons=[f"Just started: {round(elapsed * 100)}% of schedule elapsed (under 5%)."],
        )
    if progress == 0:
        return HealthRating(
            value=HealthStatus.GREEN,
            rated=True,
            reasons=[
                f"No reported progress yet; {round(elapsed * 100)}% of schedule time has elapsed."
            ],
        )

    spi = progress / max(elapsed, 0.01)
    if spi >= SPI_GREEN:
        value = HealthStatus.GREEN
    elif spi >= SPI_AMBER:
        value = HealthStatus.AMBER
    else:
        value = HealthStatus.RED

    reasons = [
        f"Progress {project.percent_complete}% vs {round(elapsed * 100)}% of schedule "
        f"elapsed (SPI {spi:.2f})."
    ]

    overdue = [t for t in tasks if t.status != TaskStatus.COMPLETED and t.end_date < today]
    if overdue:
        fraction = len(overdue) / len(tasks)
        reasons.append(f"{len(overdue)} of {len(tasks)} scheduled tasks are overdue.")
        # overdue only ever lowers a verdict, never raises it:
        if fraction > OVERDUE_RED_FRACTION:
            value = HealthStatus.RED
        elif fraction > OVERDUE_AMBER_FRACTION and value == HealthStatus.GREEN:
            value = HealthStatus.AMBER

    return HealthRating(value=value, rated=True, reasons=reasons)


def rate_budget(project: Project, spent_ledger: Decimal, today: date) -> HealthRating:
    """Budget is consumption-vs-physical-progress (from the M4 ledger only).

    The denormalized Project.budget_spent column is deliberately never read
    here — the job_costs ledger is the authoritative source.
    """
    lifecycle = _lifecycle_reason(project)
    if lifecycle is not None:
        return lifecycle

    total = Decimal(project.budget_total)
    if total <= 0:
        return _unrated("Budget cannot be rated: no budget total is configured.")

    progress = Decimal(project.percent_complete) / 100
    consumed = spent_ledger / total

    if spent_ledger == 0:
        if progress <= Decimal(ZERO_SPEND_PROGRESS):
            return HealthRating(
                value=HealthStatus.GREEN,
                rated=True,
                reasons=["Nothing spent yet and the project is early (15% or less complete)."],
            )
        return _unrated(
            f"Progress {project.percent_complete}% but zero job costs recorded — "
            "budget may be untracked."
        )

    if consumed <= progress + Decimal(BUDGET_GREEN_SLIP):
        value = HealthStatus.GREEN
    elif consumed <= progress + Decimal(BUDGET_AMBER_SLIP):
        value = HealthStatus.AMBER
    else:
        value = HealthStatus.RED

    # Hard floor: a live project that has blown its budget cannot be GREEN.
    if consumed > 1 and progress < Decimal("0.99") and value == HealthStatus.GREEN:
        value = HealthStatus.AMBER
    # Near-completion cleanup: at >=95% complete, small overruns are normal.
    if progress >= Decimal(NEAR_COMPLETION) and consumed <= progress + Decimal(BUDGET_GREEN_SLIP):
        value = HealthStatus.GREEN

    gap_pp = round(abs(float(consumed - progress)) * 100)
    direction = "ahead of" if consumed > progress else "behind"
    reasons = [
        f"Budget consumption is {gap_pp} percentage points {direction} reported physical "
        f"progress ({round(float(consumed) * 100)}% spent vs {project.percent_complete}% complete)."
    ]
    return HealthRating(value=value, rated=True, reasons=reasons)


def rate_safety() -> HealthRating:
    """Objectively NOT_RATED: no structured safety/quality data model exists yet.

    Safety never fabricates a color from free-text issues or the deprecated
    manual safety_health column. This is the explicit 'data not captured' state.
    """
    return _unrated("No safety/quality data captured yet.")


def rate_overall(timeline: HealthRating, budget: HealthRating, safety: HealthRating) -> OverallRating:
    """Worst-of-rated: the product's existing convention, conservatively applied.

    Unrated dimensions never silently drag or lift the verdict — the response
    carries the exact `basis` list the UI renders.
    """
    rated = [
        (name, rating)
        for name, rating in (("timeline", timeline), ("budget", budget), ("safety", safety))
        if rating.rated
    ]
    if not rated:
        return OverallRating(
            value=HealthStatus.NOT_RATED,
            rated=False,
            reasons=["Insufficient data for every dimension."],
            basis=[],
        )

    worst_name, worst = max(rated, key=lambda nr: _RANK[nr[1].value])
    basis = [name for name, _ in rated]
    missing = [name for name in DIMENSIONS if name not in basis]

    summary_parts = [name.capitalize() for name in basis]
    if missing:
        summary_parts.append(f"not rated: {', '.join(m.capitalize() for m in missing)}")
    reasons = [f"Overall is based on {', '.join(summary_parts)}."]
    reasons += [
        f"{name.capitalize()}: {rating.reasons[0]}"
        for name, rating in rated
        if rating.reasons and name != worst_name
    ]
    return OverallRating(value=worst.value, rated=True, reasons=reasons, basis=basis)


def compute_health(project: Project, ctx: HealthContext, today: date) -> ProjectHealthState:
    """Assemble the full health state for one project (computed + effective)."""
    if project.status == ProjectStatus.ARCHIVED:
        timeline = _unrated(ARCHIVED_REASON)
        budget = _unrated(ARCHIVED_REASON)
        safety = _unrated(ARCHIVED_REASON)
        frozen = True
    else:
        timeline = rate_timeline(project, ctx.tasks, today)
        budget = rate_budget(project, ctx.spent_ledger, today)
        safety = rate_safety()
        # COMPLETED freezes the verdict; PRE-EXECUTION statuses stay NOT_RATED.
        frozen = project.status == ProjectStatus.COMPLETED

    overall = rate_overall(timeline, budget, safety)

    now = datetime.now(timezone.utc)
    active = {}
    for ov in ctx.overrides:
        if ov.revoked_at is not None:
            continue
        if ov.expires_at is not None and ov.expires_at <= now:
            continue
        active[ov.applied_to] = ov

    def _effective(name: str) -> HealthStatus:
        target = HealthOverrideTarget(name)
        override = active.get(target)
        if override is not None:
            return HealthStatus(override.value.value)
        return timeline.value if name == "timeline" else budget.value if name == "budget" else safety.value

    return ProjectHealthState(
        project=project,
        frozen=frozen,
        timeline=timeline,
        budget=budget,
        safety=safety,
        effective_timeline=_effective("timeline"),
        effective_budget=_effective("budget"),
        effective_safety=_effective("safety"),
        overall=overall,
        effective_overall=(
            HealthStatus(active[HealthOverrideTarget.OVERALL].value)
            if HealthOverrideTarget.OVERALL in active
            else overall.value
        ),
        active_overrides=[ov for ov in ctx.overrides if ov in set(active.values())],
    )


async def load_health_contexts(
    db: AsyncSession, project_ids: list[uuid.UUID]
) -> dict[uuid.UUID, HealthContext]:
    """Batch-load every project's health inputs in a constant ~3 queries.

    Deliberately not N+1: one task query, one ledger SUM-group-by query, one
    active-override query — whatever the roll-up size (10-15 projects).
    """
    unique_ids = list(dict.fromkeys(project_ids))
    contexts: dict[uuid.UUID, HealthContext] = {
        project_id: HealthContext() for project_id in unique_ids
    }
    if not unique_ids:
        return contexts

    tasks = await db.execute(select(Task).where(Task.project_id.in_(unique_ids)))
    for task in tasks.scalars():
        contexts[task.project_id].tasks.append(task)

    ledger = await db.execute(
        select(JobCost.project_id, func.coalesce(func.sum(JobCost.amount), 0))
        .where(JobCost.project_id.in_(unique_ids))
        .group_by(JobCost.project_id)
    )
    for project_id, amount in ledger.all():
        contexts[project_id].spent_ledger = Decimal(amount)

    now = datetime.now(timezone.utc)
    overrides = await db.execute(
        select(HealthOverride)
        .where(
            HealthOverride.project_id.in_(unique_ids),
            HealthOverride.revoked_at.is_(None),
            or_(
                HealthOverride.expires_at.is_(None),
                HealthOverride.expires_at > now,
            ),
        )
    )
    for override in overrides.scalars():
        contexts[override.project_id].overrides.append(override)

    return contexts