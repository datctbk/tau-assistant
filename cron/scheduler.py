"""Cron job scheduler — executes due jobs.

Provides tick() which checks for due jobs and runs them. The gateway
calls this every 60 seconds from a background thread.

Uses a file-based lock (~/.tau/cron/.tick.lock) so only one tick
runs at a time if multiple processes overlap.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]

from cron.jobs import (
    advance_next_run,
    get_due_jobs,
    mark_job_run,
    save_job_output,
)

logger = logging.getLogger(__name__)

# Sentinel: when a cron agent has nothing new to report, it starts its
# response with this marker to suppress delivery.
SILENT_MARKER = "[SILENT]"

_TAU_HOME = Path(os.environ.get("TAU_HOME", Path.home() / ".tau"))
_LOCK_DIR = _TAU_HOME / "cron"
_LOCK_FILE = _LOCK_DIR / ".tick.lock"


def _resolve_delivery_target(job: dict) -> Optional[dict]:
    """Resolve the concrete delivery target for a cron job, if any.

    Returns a dict with {platform, chat_id} or None for local-only jobs.
    """
    deliver = job.get("deliver", "local")
    origin = job.get("origin")

    if deliver == "local":
        return None

    if deliver == "origin":
        if origin and origin.get("platform") and origin.get("chat_id"):
            return {
                "platform": origin["platform"],
                "chat_id": str(origin["chat_id"]),
            }
        return None

    if ":" in deliver:
        platform_name, chat_id = deliver.split(":", 1)
        return {
            "platform": platform_name,
            "chat_id": chat_id,
        }

    # Just a platform name — try to use origin's chat_id
    if origin and origin.get("platform") == deliver:
        return {
            "platform": deliver,
            "chat_id": str(origin["chat_id"]),
        }

    return None


def _build_job_prompt(job: dict) -> str:
    """Build the effective prompt for a cron job."""
    prompt = job.get("prompt", "")

    # Prepend cron execution guidance
    cron_hint = (
        "[SYSTEM: You are running as a scheduled cron job. "
        "DELIVERY: Your final response will be automatically delivered "
        "to the user — do NOT use send_message or try to deliver "
        "the output yourself. Just produce your report/output as your "
        "final response and the system handles the rest. "
        'SILENT: If there is genuinely nothing new to report, respond '
        'with exactly "[SILENT]" (nothing else) to suppress delivery.]'
        "\n\n"
    )
    return cron_hint + prompt


def _acquire_lock() -> Optional[int]:
    """Acquire file-based lock. Returns fd on success, None if already locked."""
    if fcntl is None:
        return None  # No locking on Windows

    _LOCK_DIR.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(_LOCK_FILE), os.O_CREAT | os.O_WRONLY, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except (OSError, IOError):
        return None


def _release_lock(fd: Optional[int]) -> None:
    """Release file-based lock."""
    if fd is None or fcntl is None:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    except (OSError, IOError):
        pass


def tick(
    run_fn=None,
    deliver_fn=None,
) -> int:
    """Check for due jobs and run them.

    Args:
        run_fn: Optional callable(job) -> (success, output_text). If None,
                jobs are marked as run without actual execution.
        deliver_fn: Optional callable(job, content) -> Optional[error_str].
                    Delivers job output to the configured target.

    Returns:
        Number of jobs executed.
    """
    lock_fd = _acquire_lock()
    if lock_fd is None and fcntl is not None:
        logger.debug("Another tick is in progress, skipping")
        return 0

    try:
        due = get_due_jobs()
        if not due:
            return 0

        executed = 0
        for job in due:
            job_id = job["id"]
            job_name = job.get("name", job_id)

            # Advance next_run for recurring jobs (at-most-once)
            advance_next_run(job_id)

            logger.info("Running job '%s' (ID: %s)", job_name, job_id)

            prompt = _build_job_prompt(job)
            success = True
            output = ""
            error_msg = None

            if run_fn:
                try:
                    success, output = run_fn(job)
                except Exception as e:
                    success = False
                    output = f"Job execution failed: {e}"
                    error_msg = str(e)
                    logger.error("Job '%s' failed: %s", job_name, e)

            # Save output
            if output:
                try:
                    save_job_output(job_id, output)
                except Exception as e:
                    logger.error("Failed to save output for job '%s': %s", job_name, e)

            # Deliver result (if not silent and not local-only)
            delivery_error = None
            if (
                success
                and output
                and not output.strip().startswith(SILENT_MARKER)
                and deliver_fn
            ):
                target = _resolve_delivery_target(job)
                if target:
                    try:
                        delivery_error = deliver_fn(job, output)
                        if delivery_error:
                            logger.warning(
                                "Job '%s' delivery failed: %s",
                                job_name, delivery_error,
                            )
                    except Exception as e:
                        delivery_error = str(e)
                        logger.error(
                            "Job '%s' delivery exception: %s", job_name, e,
                        )

            # Mark the run
            mark_job_run(
                job_id,
                success=success,
                error=error_msg,
                delivery_error=delivery_error,
            )
            executed += 1

        return executed

    finally:
        _release_lock(lock_fd)
