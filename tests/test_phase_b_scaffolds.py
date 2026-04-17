from __future__ import annotations

from datetime import datetime, timedelta, timezone

from profile import UserProfile
from planner import PlanStep, WorkflowPlan
from routine_engine import Routine, RoutineEngine
from workflow_runner import WorkflowRunner


def test_profile_save_load(tmp_path):
    p = UserProfile(name="Dat", goals=["ship"], preferences={"tone": "concise"})
    p.save(str(tmp_path))
    loaded = UserProfile.load(str(tmp_path))
    assert loaded.name == "Dat"
    assert loaded.goals == ["ship"]


def test_planner_topological_order():
    plan = WorkflowPlan(
        id="w1",
        objective="build",
        steps=[
            PlanStep(id="s1", title="design"),
            PlanStep(id="s2", title="implement", depends_on=["s1"]),
            PlanStep(id="s3", title="test", depends_on=["s2"]),
        ],
    )
    assert plan.topo_order() == ["s1", "s2", "s3"]


def test_planner_cycle_detected():
    plan = WorkflowPlan(
        id="w2",
        objective="cycle",
        steps=[
            PlanStep(id="a", title="a", depends_on=["b"]),
            PlanStep(id="b", title="b", depends_on=["a"]),
        ],
    )
    try:
        plan.topo_order()
        assert False, "Expected cycle error"
    except ValueError as e:
        assert "cycle" in str(e).lower()


def test_routine_due_and_mark_run():
    now = datetime.now(timezone.utc)
    eng = RoutineEngine(
        routines=[
            Routine(id="r1", title="daily brief", interval_minutes=60),
        ]
    )
    due = eng.due_routines(now)
    assert len(due) == 1 and due[0].id == "r1"

    eng.mark_run("r1", now)
    due2 = eng.due_routines(now + timedelta(minutes=10))
    assert due2 == []

    due3 = eng.due_routines(now + timedelta(minutes=61))
    assert len(due3) == 1 and due3[0].id == "r1"


def test_workflow_runner_checkpoints_and_events(tmp_path):
    plan = WorkflowPlan(
        id="wf1",
        objective="demo",
        steps=[
            PlanStep(id="s1", title="a"),
            PlanStep(id="s2", title="b", depends_on=["s1"]),
        ],
    )
    runner = WorkflowRunner(str(tmp_path), session_id="sess-1")

    outcomes = runner.run(plan, execute_step=lambda sid: f"done-{sid}")
    assert len(outcomes) == 2
    assert outcomes[0]["step_id"] == "s1"
    assert outcomes[1]["step_id"] == "s2"

    cp_dir = tmp_path / ".tau" / "checkpoints"
    assert cp_dir.exists()
    assert len(list(cp_dir.glob("*.json"))) == 2

    evt_file = tmp_path / ".tau" / "events" / "assistant-events.jsonl"
    txt = evt_file.read_text(encoding="utf-8")
    assert '"name": "step_started"' in txt
    assert '"name": "step_completed"' in txt


def test_routine_scheduler_executes_due_callback():
    now = datetime.now(timezone.utc)
    eng = RoutineEngine(routines=[Routine(id="r1", title="brief", interval_minutes=1)])
    hits = []

    def _on_due(r):
        hits.append(r.id)

    eng.start_scheduler(on_due=_on_due, poll_interval_seconds=0.1)
    try:
        import time as _time
        _time.sleep(0.25)
    finally:
        eng.stop_scheduler()

    assert "r1" in hits
