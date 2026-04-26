"""Cron job management tools for Tau Agent.

Exposes a single compressed action-oriented tool to avoid schema/context bloat.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from cron.jobs import (
    create_job,
    get_job,
    list_jobs,
    parse_schedule,
    pause_job,
    remove_job,
    resume_job,
    trigger_job,
    update_job,
)

# ── Prompt injection scanning ──────────────────────────────────────────

_CRON_THREAT_PATTERNS = [
    (r"ignore\s+(?:\w+\s+)*(?:previous|all|above|prior)\s+(?:\w+\s+)*instructions", "prompt_injection"),
    (r"do\s+not\s+tell\s+the\s+user", "deception_hide"),
    (r"system\s+prompt\s+override", "sys_prompt_override"),
    (r"disregard\s+(your|all|any)\s+(instructions|rules|guidelines)", "disregard_rules"),
    (r"curl\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)", "exfil_curl"),
    (r"wget\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)", "exfil_wget"),
    (r"cat\s+[^\n]*(\.env|credentials|\.netrc|\.pgpass)", "read_secrets"),
    (r"authorized_keys", "ssh_backdoor"),
    (r"/etc/sudoers|visudo", "sudoers_mod"),
    (r"rm\s+-rf\s+/", "destructive_root_rm"),
]

_CRON_INVISIBLE_CHARS = {
    "\u200b", "\u200c", "\u200d", "\u2060", "\ufeff",
    "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",
}


def _scan_cron_prompt(prompt: str) -> str:
    """Scan a cron prompt for critical threats.

    Returns error string if blocked, else empty string.
    """
    for char in _CRON_INVISIBLE_CHARS:
        if char in prompt:
            return f"Blocked: prompt contains invisible unicode U+{ord(char):04X} (possible injection)."
    for pattern, pid in _CRON_THREAT_PATTERNS:
        if re.search(pattern, prompt, re.IGNORECASE):
            return (
                f"Blocked: prompt matches threat pattern '{pid}'. "
                f"Cron prompts must not contain injection or exfiltration payloads."
            )
    return ""


# ── Formatting helpers ──────────────────────────────────────────────────


def _repeat_display(job: Dict[str, Any]) -> str:
    times = (job.get("repeat") or {}).get("times")
    completed = (job.get("repeat") or {}).get("completed", 0)
    if times is None:
        return "forever"
    if times == 1:
        return "once" if completed == 0 else "1/1"
    return f"{completed}/{times}" if completed else f"{times} times"


def _format_job(job: Dict[str, Any]) -> Dict[str, Any]:
    prompt = job.get("prompt", "")
    return {
        "job_id": job["id"],
        "name": job["name"],
        "prompt_preview": prompt[:100] + "..." if len(prompt) > 100 else prompt,
        "model": job.get("model"),
        "provider": job.get("provider"),
        "schedule": job.get("schedule_display"),
        "repeat": _repeat_display(job),
        "deliver": job.get("deliver", "local"),
        "next_run_at": job.get("next_run_at"),
        "last_run_at": job.get("last_run_at"),
        "last_status": job.get("last_status"),
        "last_delivery_error": job.get("last_delivery_error"),
        "enabled": job.get("enabled", True),
        "state": job.get("state", "scheduled" if job.get("enabled", True) else "paused"),
        "paused_at": job.get("paused_at"),
        "paused_reason": job.get("paused_reason"),
    }


def _tool_error(message: str) -> str:
    return json.dumps({"success": False, "error": message}, indent=2)


# ── Main tool function ──────────────────────────────────────────────────


def cronjob(
    action: str,
    job_id: Optional[str] = None,
    prompt: Optional[str] = None,
    schedule: Optional[str] = None,
    name: Optional[str] = None,
    repeat: Optional[int] = None,
    deliver: Optional[str] = None,
    include_disabled: bool = False,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    reason: Optional[str] = None,
) -> str:
    """Unified cron job management tool."""
    try:
        normalized = (action or "").strip().lower()

        if normalized == "create":
            if not schedule:
                return _tool_error("schedule is required for create")
            if not prompt:
                return _tool_error("create requires a prompt")
            scan_error = _scan_cron_prompt(prompt)
            if scan_error:
                return _tool_error(scan_error)

            job = create_job(
                prompt=prompt,
                schedule=schedule,
                name=name,
                repeat=repeat,
                deliver=deliver,
                model=model,
                provider=provider,
            )
            return json.dumps(
                {
                    "success": True,
                    "job_id": job["id"],
                    "name": job["name"],
                    "schedule": job["schedule_display"],
                    "repeat": _repeat_display(job),
                    "deliver": job.get("deliver", "local"),
                    "next_run_at": job["next_run_at"],
                    "job": _format_job(job),
                    "message": f"Cron job '{job['name']}' created.",
                },
                indent=2,
            )

        if normalized == "list":
            jobs = [
                _format_job(job)
                for job in list_jobs(include_disabled=include_disabled)
            ]
            return json.dumps(
                {"success": True, "count": len(jobs), "jobs": jobs}, indent=2,
            )

        if not job_id:
            return _tool_error(f"job_id is required for action '{normalized}'")

        job = get_job(job_id)
        if not job:
            return _tool_error(f"Job with ID '{job_id}' not found.")

        if normalized == "remove":
            removed = remove_job(job_id)
            if not removed:
                return _tool_error(f"Failed to remove job '{job_id}'")
            return json.dumps(
                {
                    "success": True,
                    "message": f"Cron job '{job['name']}' removed.",
                    "removed_job": {
                        "id": job_id,
                        "name": job["name"],
                        "schedule": job.get("schedule_display"),
                    },
                },
                indent=2,
            )

        if normalized == "pause":
            updated = pause_job(job_id, reason=reason)
            return json.dumps({"success": True, "job": _format_job(updated)}, indent=2)

        if normalized == "resume":
            updated = resume_job(job_id)
            return json.dumps({"success": True, "job": _format_job(updated)}, indent=2)

        if normalized in {"run", "run_now", "trigger"}:
            updated = trigger_job(job_id)
            return json.dumps({"success": True, "job": _format_job(updated)}, indent=2)

        if normalized == "update":
            updates: Dict[str, Any] = {}
            if prompt is not None:
                scan_error = _scan_cron_prompt(prompt)
                if scan_error:
                    return _tool_error(scan_error)
                updates["prompt"] = prompt
            if name is not None:
                updates["name"] = name
            if deliver is not None:
                updates["deliver"] = deliver
            if model is not None:
                updates["model"] = model
            if provider is not None:
                updates["provider"] = provider
            if repeat is not None:
                normalized_repeat = None if repeat <= 0 else repeat
                repeat_state = dict(job.get("repeat") or {})
                repeat_state["times"] = normalized_repeat
                updates["repeat"] = repeat_state
            if schedule is not None:
                parsed_schedule = parse_schedule(schedule)
                updates["schedule"] = parsed_schedule
                updates["schedule_display"] = parsed_schedule.get("display", schedule)
            if not updates:
                return _tool_error("No updates provided.")
            updated = update_job(job_id, updates)
            return json.dumps({"success": True, "job": _format_job(updated)}, indent=2)

        return _tool_error(f"Unknown cron action '{action}'")

    except Exception as e:
        return _tool_error(str(e))


# ── Tool schema ─────────────────────────────────────────────────────────

CRONJOB_SCHEMA = {
    "name": "cronjob",
    "description": (
        "Manage scheduled cron jobs. Actions: create, list, update, pause, resume, remove, run. "
        "Jobs run in fresh sessions with no chat context — prompts must be self-contained."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "One of: create, list, update, pause, resume, remove, run",
            },
            "job_id": {
                "type": "string",
                "description": "Required for update/pause/resume/remove/run",
            },
            "prompt": {
                "type": "string",
                "description": "For create: the full self-contained prompt.",
            },
            "schedule": {
                "type": "string",
                "description": "For create/update: '30m', 'every 2h', '0 9 * * *', or ISO timestamp",
            },
            "name": {"type": "string", "description": "Optional human-friendly name"},
            "repeat": {
                "type": "integer",
                "description": "Optional repeat count. Omit for defaults.",
            },
            "deliver": {
                "type": "string",
                "description": "'origin', 'local', or 'platform:chat_id'",
            },
            "model": {"type": "string", "description": "Optional per-job model override"},
            "provider": {"type": "string", "description": "Optional provider override"},
        },
        "required": ["action"],
    },
}
