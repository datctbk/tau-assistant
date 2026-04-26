"""Cron job storage and management.

Jobs are stored in ~/.tau/cron/jobs.json
Output is saved to ~/.tau/cron/output/{job_id}/{timestamp}.md
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from croniter import croniter

    HAS_CRONITER = True
except ImportError:
    HAS_CRONITER = False


def _now() -> datetime:
    """Return current time as timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


# =============================================================================
# Configuration
# =============================================================================

_TAU_HOME = Path(os.environ.get("TAU_HOME", Path.home() / ".tau"))
CRON_DIR = _TAU_HOME / "cron"
JOBS_FILE = CRON_DIR / "jobs.json"
OUTPUT_DIR = CRON_DIR / "output"
ONESHOT_GRACE_SECONDS = 120


def _secure_dir(path: Path) -> None:
    """Set directory to owner-only access (0700)."""
    try:
        os.chmod(path, 0o700)
    except (OSError, NotImplementedError):
        pass


def _secure_file(path: Path) -> None:
    """Set file to owner-only read/write (0600)."""
    try:
        if path.exists():
            os.chmod(path, 0o600)
    except (OSError, NotImplementedError):
        pass


def ensure_dirs() -> None:
    """Ensure cron directories exist with secure permissions."""
    CRON_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _secure_dir(CRON_DIR)
    _secure_dir(OUTPUT_DIR)


# =============================================================================
# Schedule Parsing
# =============================================================================


def parse_duration(s: str) -> int:
    """Parse duration string into minutes.

    Examples:
        "30m" → 30
        "2h"  → 120
        "1d"  → 1440
    """
    s = s.strip().lower()
    match = re.match(
        r"^(\d+)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)$", s,
    )
    if not match:
        raise ValueError(
            f"Invalid duration: '{s}'. Use format like '30m', '2h', or '1d'"
        )

    value = int(match.group(1))
    unit = match.group(2)[0]

    multipliers = {"m": 1, "h": 60, "d": 1440}
    return value * multipliers[unit]


def parse_schedule(schedule: str) -> Dict[str, Any]:
    """Parse schedule string into structured format.

    Returns dict with:
        - kind: "once" | "interval" | "cron"
        - For "once": "run_at" (ISO timestamp)
        - For "interval": "minutes" (int)
        - For "cron": "expr" (cron expression)

    Examples:
        "30m"              → once in 30 minutes
        "every 30m"        → recurring every 30 minutes
        "0 9 * * *"        → cron expression
        "2026-02-03T14:00" → once at timestamp
    """
    schedule = schedule.strip()
    original = schedule
    schedule_lower = schedule.lower()

    # "every X" pattern → recurring interval
    if schedule_lower.startswith("every "):
        duration_str = schedule[6:].strip()
        minutes = parse_duration(duration_str)
        return {
            "kind": "interval",
            "minutes": minutes,
            "display": f"every {minutes}m",
        }

    # Check for cron expression (5 or 6 space-separated fields)
    parts = schedule.split()
    if len(parts) >= 5 and all(
        re.match(r"^[\d\*\-,/]+$", p) for p in parts[:5]
    ):
        if not HAS_CRONITER:
            raise ValueError(
                "Cron expressions require 'croniter' package. "
                "Install with: pip install croniter"
            )
        try:
            croniter(schedule)
        except Exception as e:
            raise ValueError(f"Invalid cron expression '{schedule}': {e}")
        return {"kind": "cron", "expr": schedule, "display": schedule}

    # ISO timestamp
    if "T" in schedule or re.match(r"^\d{4}-\d{2}-\d{2}", schedule):
        try:
            dt = datetime.fromisoformat(schedule.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.astimezone()
            return {
                "kind": "once",
                "run_at": dt.isoformat(),
                "display": f"once at {dt.strftime('%Y-%m-%d %H:%M')}",
            }
        except ValueError as e:
            raise ValueError(f"Invalid timestamp '{schedule}': {e}")

    # Duration like "30m", "2h" → one-shot from now
    try:
        minutes = parse_duration(schedule)
        run_at = _now() + timedelta(minutes=minutes)
        return {
            "kind": "once",
            "run_at": run_at.isoformat(),
            "display": f"once in {original}",
        }
    except ValueError:
        pass

    raise ValueError(
        f"Invalid schedule '{original}'. Use:\n"
        f"  - Duration: '30m', '2h', '1d' (one-shot)\n"
        f"  - Interval: 'every 30m', 'every 2h' (recurring)\n"
        f"  - Cron: '0 9 * * *' (cron expression)\n"
        f"  - Timestamp: '2026-02-03T14:00:00' (one-shot at time)"
    )


def _ensure_aware(dt: datetime) -> datetime:
    """Return a timezone-aware datetime. Interpret naive as UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _compute_grace_seconds(schedule: dict) -> int:
    """Compute how late a job can be and still catch up.

    Uses half the schedule period, clamped between 120s and 2h.
    """
    MIN_GRACE = 120
    MAX_GRACE = 7200

    kind = schedule.get("kind")

    if kind == "interval":
        period_seconds = schedule.get("minutes", 1) * 60
        grace = period_seconds // 2
        return max(MIN_GRACE, min(grace, MAX_GRACE))

    if kind == "cron" and HAS_CRONITER:
        try:
            now = _now()
            cron = croniter(schedule["expr"], now)
            first = cron.get_next(datetime)
            second = cron.get_next(datetime)
            period_seconds = int((second - first).total_seconds())
            grace = period_seconds // 2
            return max(MIN_GRACE, min(grace, MAX_GRACE))
        except Exception:
            pass

    return MIN_GRACE


def compute_next_run(
    schedule: Dict[str, Any],
    last_run_at: Optional[str] = None,
) -> Optional[str]:
    """Compute the next run time for a schedule.

    Returns ISO timestamp string, or None if no more runs.
    """
    now = _now()

    if schedule["kind"] == "once":
        if last_run_at:
            return None  # One-shot already ran
        run_at = schedule.get("run_at")
        if run_at:
            run_at_dt = _ensure_aware(datetime.fromisoformat(run_at))
            if run_at_dt >= now - timedelta(seconds=ONESHOT_GRACE_SECONDS):
                return run_at
        return None

    elif schedule["kind"] == "interval":
        minutes = schedule["minutes"]
        if last_run_at:
            last = _ensure_aware(datetime.fromisoformat(last_run_at))
            next_run = last + timedelta(minutes=minutes)
        else:
            next_run = now + timedelta(minutes=minutes)
        return next_run.isoformat()

    elif schedule["kind"] == "cron":
        if not HAS_CRONITER:
            return None
        cron = croniter(schedule["expr"], now)
        next_run = cron.get_next(datetime)
        return next_run.isoformat()

    return None


# =============================================================================
# Job CRUD Operations
# =============================================================================


def load_jobs() -> List[Dict[str, Any]]:
    """Load all jobs from storage."""
    ensure_dirs()
    if not JOBS_FILE.exists():
        return []

    try:
        with open(JOBS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("jobs", [])
    except json.JSONDecodeError:
        try:
            with open(JOBS_FILE, "r", encoding="utf-8") as f:
                data = json.loads(f.read(), strict=False)
                jobs = data.get("jobs", [])
                if jobs:
                    save_jobs(jobs)
                    logger.warning("Auto-repaired jobs.json (had invalid control characters)")
                return jobs
        except Exception as e:
            logger.error("Failed to auto-repair jobs.json: %s", e)
            raise RuntimeError(f"Cron database corrupted: {e}") from e
    except IOError as e:
        logger.error("IOError reading jobs.json: %s", e)
        raise RuntimeError(f"Failed to read cron database: {e}") from e


def save_jobs(jobs: List[Dict[str, Any]]) -> None:
    """Save all jobs to storage atomically (tempfile + replace + fsync)."""
    ensure_dirs()
    fd, tmp_path = tempfile.mkstemp(
        dir=str(JOBS_FILE.parent), suffix=".tmp", prefix=".jobs_",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(
                {"jobs": jobs, "updated_at": _now().isoformat()},
                f,
                indent=2,
            )
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, JOBS_FILE)
        _secure_file(JOBS_FILE)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def create_job(
    prompt: str,
    schedule: str,
    name: Optional[str] = None,
    repeat: Optional[int] = None,
    deliver: Optional[str] = None,
    origin: Optional[Dict[str, Any]] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new cron job.

    Args:
        prompt: The prompt to run (must be self-contained).
        schedule: Schedule string (see parse_schedule).
        name: Optional friendly name.
        repeat: How many times to run (None = forever, 1 = once).
        deliver: Where to deliver output ("origin", "local", "telegram", etc.).
        origin: Source info where job was created.
        model: Optional per-job model override.
        provider: Optional per-job provider override.
    """
    parsed_schedule = parse_schedule(schedule)

    if repeat is not None and repeat <= 0:
        repeat = None

    if parsed_schedule["kind"] == "once" and repeat is None:
        repeat = 1

    if deliver is None:
        deliver = "origin" if origin else "local"

    job_id = uuid.uuid4().hex[:12]
    now = _now().isoformat()

    job = {
        "id": job_id,
        "name": name or prompt[:50].strip(),
        "prompt": prompt,
        "model": model,
        "provider": provider,
        "schedule": parsed_schedule,
        "schedule_display": parsed_schedule.get("display", schedule),
        "repeat": {
            "times": repeat,
            "completed": 0,
        },
        "enabled": True,
        "state": "scheduled",
        "paused_at": None,
        "paused_reason": None,
        "created_at": now,
        "next_run_at": compute_next_run(parsed_schedule),
        "last_run_at": None,
        "last_status": None,
        "last_error": None,
        "last_delivery_error": None,
        "deliver": deliver,
        "origin": origin,
    }

    jobs = load_jobs()
    jobs.append(job)
    save_jobs(jobs)

    return job


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Get a job by ID."""
    jobs = load_jobs()
    for job in jobs:
        if job["id"] == job_id:
            return job
    return None


def list_jobs(include_disabled: bool = False) -> List[Dict[str, Any]]:
    """List all jobs, optionally including disabled ones."""
    jobs = load_jobs()
    if not include_disabled:
        jobs = [j for j in jobs if j.get("enabled", True)]
    return jobs


def update_job(
    job_id: str, updates: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Update a job by ID, refreshing derived schedule fields when needed."""
    jobs = load_jobs()
    for i, job in enumerate(jobs):
        if job["id"] != job_id:
            continue

        updated = {**job, **updates}
        schedule_changed = "schedule" in updates

        if schedule_changed:
            updated_schedule = updated["schedule"]
            updated["schedule_display"] = updates.get(
                "schedule_display",
                updated_schedule.get("display", updated.get("schedule_display")),
            )
            if updated.get("state") != "paused":
                updated["next_run_at"] = compute_next_run(updated_schedule)

        if (
            updated.get("enabled", True)
            and updated.get("state") != "paused"
            and not updated.get("next_run_at")
        ):
            updated["next_run_at"] = compute_next_run(updated["schedule"])

        jobs[i] = updated
        save_jobs(jobs)
        return jobs[i]
    return None


def pause_job(
    job_id: str, reason: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Pause a job without deleting it."""
    return update_job(
        job_id,
        {
            "enabled": False,
            "state": "paused",
            "paused_at": _now().isoformat(),
            "paused_reason": reason,
        },
    )


def resume_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Resume a paused job and compute the next future run from now."""
    job = get_job(job_id)
    if not job:
        return None

    next_run_at = compute_next_run(job["schedule"])
    return update_job(
        job_id,
        {
            "enabled": True,
            "state": "scheduled",
            "paused_at": None,
            "paused_reason": None,
            "next_run_at": next_run_at,
        },
    )


def trigger_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Schedule a job to run on the next scheduler tick."""
    job = get_job(job_id)
    if not job:
        return None
    return update_job(
        job_id,
        {
            "enabled": True,
            "state": "scheduled",
            "paused_at": None,
            "paused_reason": None,
            "next_run_at": _now().isoformat(),
        },
    )


def remove_job(job_id: str) -> bool:
    """Remove a job by ID."""
    jobs = load_jobs()
    original_len = len(jobs)
    jobs = [j for j in jobs if j["id"] != job_id]
    if len(jobs) < original_len:
        save_jobs(jobs)
        return True
    return False


def mark_job_run(
    job_id: str,
    success: bool,
    error: Optional[str] = None,
    delivery_error: Optional[str] = None,
) -> None:
    """Mark a job as having been run.

    Updates last_run_at, last_status, increments completed count,
    computes next_run_at, and auto-removes if repeat limit reached.
    """
    jobs = load_jobs()
    for i, job in enumerate(jobs):
        if job["id"] == job_id:
            now = _now().isoformat()
            job["last_run_at"] = now
            job["last_status"] = "ok" if success else "error"
            job["last_error"] = error if not success else None
            job["last_delivery_error"] = delivery_error

            if job.get("repeat"):
                job["repeat"]["completed"] = job["repeat"].get("completed", 0) + 1

                times = job["repeat"].get("times")
                completed = job["repeat"]["completed"]
                if times is not None and times > 0 and completed >= times:
                    jobs.pop(i)
                    save_jobs(jobs)
                    return

            job["next_run_at"] = compute_next_run(job["schedule"], now)

            if job["next_run_at"] is None:
                job["enabled"] = False
                job["state"] = "completed"
            elif job.get("state") != "paused":
                job["state"] = "scheduled"

            save_jobs(jobs)
            return

    logger.warning("mark_job_run: job_id %s not found", job_id)


def advance_next_run(job_id: str) -> bool:
    """Preemptively advance next_run_at for a recurring job before execution.

    This converts the scheduler from at-least-once to at-most-once for
    recurring jobs — missing one run is better than firing dozens in a crash loop.
    """
    jobs = load_jobs()
    for job in jobs:
        if job["id"] == job_id:
            kind = job.get("schedule", {}).get("kind")
            if kind not in ("cron", "interval"):
                return False
            now = _now().isoformat()
            new_next = compute_next_run(job["schedule"], now)
            if new_next and new_next != job.get("next_run_at"):
                job["next_run_at"] = new_next
                save_jobs(jobs)
                return True
            return False
    return False


def get_due_jobs() -> List[Dict[str, Any]]:
    """Get all jobs that are due to run now.

    For recurring jobs, if the scheduled time is stale (gateway was down),
    fast-forwards to the next future run instead of firing a stale run.
    """
    now = _now()
    raw_jobs = load_jobs()
    jobs = copy.deepcopy(raw_jobs)
    due = []
    needs_save = False

    for job in jobs:
        if not job.get("enabled", True):
            continue

        next_run = job.get("next_run_at")
        if not next_run:
            continue

        next_run_dt = _ensure_aware(datetime.fromisoformat(next_run))
        if next_run_dt <= now:
            schedule = job.get("schedule", {})
            kind = schedule.get("kind")

            # Check if stale (missed the window)
            grace = _compute_grace_seconds(schedule)
            if (
                kind in ("cron", "interval")
                and (now - next_run_dt).total_seconds() > grace
            ):
                new_next = compute_next_run(schedule, now.isoformat())
                if new_next:
                    logger.info(
                        "Job '%s' missed its scheduled time (%s). "
                        "Fast-forwarding to: %s",
                        job.get("name", job["id"]),
                        next_run,
                        new_next,
                    )
                    for rj in raw_jobs:
                        if rj["id"] == job["id"]:
                            rj["next_run_at"] = new_next
                            needs_save = True
                            break
                    continue

            due.append(job)

    if needs_save:
        save_jobs(raw_jobs)

    return due


def save_job_output(job_id: str, output: str) -> Path:
    """Save job output to file."""
    ensure_dirs()
    job_output_dir = OUTPUT_DIR / job_id
    job_output_dir.mkdir(parents=True, exist_ok=True)
    _secure_dir(job_output_dir)

    timestamp = _now().strftime("%Y-%m-%d_%H-%M-%S")
    output_file = job_output_dir / f"{timestamp}.md"

    fd, tmp_path = tempfile.mkstemp(
        dir=str(job_output_dir), suffix=".tmp", prefix=".output_",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(output)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, output_file)
        _secure_file(output_file)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return output_file
