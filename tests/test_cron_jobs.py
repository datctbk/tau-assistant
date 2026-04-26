"""Tests for tau-assistant cron job storage and management."""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

# Add tau-assistant to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cron.jobs import (
    _compute_grace_seconds,
    _ensure_aware,
    compute_next_run,
    create_job,
    get_due_jobs,
    get_job,
    list_jobs,
    load_jobs,
    mark_job_run,
    parse_duration,
    parse_schedule,
    pause_job,
    remove_job,
    resume_job,
    save_jobs,
    trigger_job,
    update_job,
    advance_next_run,
    save_job_output,
)


@pytest.fixture(autouse=True)
def temp_cron_dir(tmp_path, monkeypatch):
    """Redirect cron storage to a temp directory."""
    import cron.jobs as jobs_mod

    monkeypatch.setattr(jobs_mod, "CRON_DIR", tmp_path / "cron")
    monkeypatch.setattr(jobs_mod, "JOBS_FILE", tmp_path / "cron" / "jobs.json")
    monkeypatch.setattr(jobs_mod, "OUTPUT_DIR", tmp_path / "cron" / "output")
    return tmp_path


# ── Schedule Parsing ────────────────────────────────────────────────────


class TestParseDuration:
    def test_minutes(self):
        assert parse_duration("30m") == 30
        assert parse_duration("5min") == 5
        assert parse_duration("1minute") == 1

    def test_hours(self):
        assert parse_duration("2h") == 120
        assert parse_duration("1hour") == 60

    def test_days(self):
        assert parse_duration("1d") == 1440

    def test_invalid(self):
        with pytest.raises(ValueError):
            parse_duration("abc")
        with pytest.raises(ValueError):
            parse_duration("30x")


class TestParseSchedule:
    def test_one_shot_duration(self):
        result = parse_schedule("30m")
        assert result["kind"] == "once"
        assert "run_at" in result

    def test_interval(self):
        result = parse_schedule("every 2h")
        assert result["kind"] == "interval"
        assert result["minutes"] == 120

    def test_iso_timestamp(self):
        result = parse_schedule("2026-06-01T09:00:00")
        assert result["kind"] == "once"
        assert "run_at" in result

    def test_invalid(self):
        with pytest.raises(ValueError):
            parse_schedule("not-a-schedule")


class TestComputeNextRun:
    def test_once_no_last_run(self):
        schedule = {"kind": "once", "run_at": datetime.now(timezone.utc).isoformat()}
        result = compute_next_run(schedule)
        assert result is not None

    def test_once_already_ran(self):
        schedule = {"kind": "once", "run_at": datetime.now(timezone.utc).isoformat()}
        result = compute_next_run(schedule, last_run_at=datetime.now(timezone.utc).isoformat())
        assert result is None

    def test_interval_first_run(self):
        schedule = {"kind": "interval", "minutes": 30}
        result = compute_next_run(schedule)
        assert result is not None
        dt = datetime.fromisoformat(result)
        assert dt > datetime.now(timezone.utc)

    def test_interval_after_run(self):
        last = datetime.now(timezone.utc).isoformat()
        schedule = {"kind": "interval", "minutes": 60}
        result = compute_next_run(schedule, last_run_at=last)
        assert result is not None


# ── Job CRUD ────────────────────────────────────────────────────────────


class TestJobCRUD:
    def test_create_and_get(self):
        job = create_job(
            prompt="Test prompt",
            schedule="every 30m",
            name="Test Job",
        )
        assert job["id"]
        assert job["name"] == "Test Job"
        assert job["schedule"]["kind"] == "interval"

        loaded = get_job(job["id"])
        assert loaded is not None
        assert loaded["id"] == job["id"]

    def test_list_jobs(self):
        create_job(prompt="Job 1", schedule="every 1h")
        create_job(prompt="Job 2", schedule="every 2h")
        jobs = list_jobs()
        assert len(jobs) == 2

    def test_list_excludes_disabled(self):
        job = create_job(prompt="Job 1", schedule="every 1h")
        pause_job(job["id"])
        jobs = list_jobs(include_disabled=False)
        assert len(jobs) == 0
        jobs = list_jobs(include_disabled=True)
        assert len(jobs) == 1

    def test_update(self):
        job = create_job(prompt="Original", schedule="every 1h")
        updated = update_job(job["id"], {"name": "Updated Name"})
        assert updated["name"] == "Updated Name"

    def test_remove(self):
        job = create_job(prompt="To remove", schedule="every 1h")
        assert remove_job(job["id"]) is True
        assert get_job(job["id"]) is None
        assert remove_job("nonexistent") is False

    def test_pause_and_resume(self):
        job = create_job(prompt="Pausable", schedule="every 1h")
        paused = pause_job(job["id"], reason="Testing")
        assert paused["state"] == "paused"
        assert paused["enabled"] is False
        assert paused["paused_reason"] == "Testing"

        resumed = resume_job(job["id"])
        assert resumed["state"] == "scheduled"
        assert resumed["enabled"] is True

    def test_trigger(self):
        job = create_job(prompt="Triggerable", schedule="every 1h")
        triggered = trigger_job(job["id"])
        assert triggered["state"] == "scheduled"
        # next_run_at should be now or very close
        next_dt = datetime.fromisoformat(triggered["next_run_at"])
        assert abs((next_dt - datetime.now(timezone.utc)).total_seconds()) < 5


class TestMarkJobRun:
    def test_success(self):
        job = create_job(prompt="Test", schedule="every 1h")
        mark_job_run(job["id"], success=True)
        loaded = get_job(job["id"])
        assert loaded["last_status"] == "ok"
        assert loaded["last_run_at"] is not None
        assert loaded["repeat"]["completed"] == 1

    def test_error(self):
        job = create_job(prompt="Test", schedule="every 1h")
        mark_job_run(job["id"], success=False, error="Something failed")
        loaded = get_job(job["id"])
        assert loaded["last_status"] == "error"
        assert loaded["last_error"] == "Something failed"

    def test_one_shot_auto_removes(self):
        job = create_job(prompt="Once", schedule="30m")
        assert job["repeat"]["times"] == 1
        mark_job_run(job["id"], success=True)
        assert get_job(job["id"]) is None  # auto-removed

    def test_delivery_error_tracked(self):
        job = create_job(prompt="Test", schedule="every 1h")
        mark_job_run(job["id"], success=True, delivery_error="Platform down")
        loaded = get_job(job["id"])
        assert loaded["last_delivery_error"] == "Platform down"


class TestGetDueJobs:
    def test_due_interval(self):
        job = create_job(prompt="Due", schedule="every 1h")
        # Set next_run to the past
        update_job(job["id"], {"next_run_at": (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()})
        due = get_due_jobs()
        assert len(due) == 1
        assert due[0]["id"] == job["id"]

    def test_not_due_yet(self):
        create_job(prompt="Future", schedule="every 1h")
        due = get_due_jobs()
        assert len(due) == 0

    def test_disabled_not_due(self):
        job = create_job(prompt="Disabled", schedule="every 1h")
        update_job(job["id"], {"next_run_at": (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()})
        pause_job(job["id"])
        due = get_due_jobs()
        assert len(due) == 0


class TestAdvanceNextRun:
    def test_advance_interval(self):
        job = create_job(prompt="Test", schedule="every 1h")
        original_next = job["next_run_at"]
        advanced = advance_next_run(job["id"])
        # May or may not advance depending on timing
        assert isinstance(advanced, bool)

    def test_advance_one_shot_no_change(self):
        job = create_job(prompt="Once", schedule="30m")
        assert advance_next_run(job["id"]) is False


class TestSaveJobOutput:
    def test_save(self):
        path = save_job_output("test-job", "# Output\n\nResults here.")
        assert path.exists()
        assert path.read_text() == "# Output\n\nResults here."
        assert path.suffix == ".md"


class TestEnsureAware:
    def test_naive_becomes_utc(self):
        naive = datetime(2026, 1, 1, 12, 0, 0)
        aware = _ensure_aware(naive)
        assert aware.tzinfo is not None

    def test_aware_unchanged(self):
        aware = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = _ensure_aware(aware)
        assert result == aware


class TestComputeGrace:
    def test_interval_grace(self):
        schedule = {"kind": "interval", "minutes": 60}
        grace = _compute_grace_seconds(schedule)
        assert grace == 1800  # 30 minutes = half of 60m

    def test_short_interval(self):
        schedule = {"kind": "interval", "minutes": 1}
        grace = _compute_grace_seconds(schedule)
        assert grace == 120  # clamped to minimum

    def test_long_interval(self):
        schedule = {"kind": "interval", "minutes": 1440}  # 24h
        grace = _compute_grace_seconds(schedule)
        assert grace == 7200  # clamped to maximum
