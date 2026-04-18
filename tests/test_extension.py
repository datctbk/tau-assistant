from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import importlib.util


ROOT = Path(__file__).resolve().parent.parent
TAU_ROOT = ROOT.parent / "tau"
sys.path.insert(0, str(TAU_ROOT))

_mod_name = "_tau_ext_assistant_ext"
_spec = importlib.util.spec_from_file_location(
    _mod_name,
    str(ROOT / "extensions" / "assistant" / "extension.py"),
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_mod_name] = _mod
_spec.loader.exec_module(_mod)

AssistantExtension = _mod.AssistantExtension


class _FakeSubSession:
    def __init__(self, events):
        self._events = events

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def prompt(self, task):
        del task
        return list(self._events)


def _ctx_with_workspace(workspace: str) -> MagicMock:
    ctx = MagicMock()
    ctx.print = MagicMock()
    ctx.enqueue = MagicMock()
    cfg = MagicMock()
    cfg.workspace_root = workspace
    ctx._agent_config = cfg
    return ctx


def test_manifest():
    assert AssistantExtension.manifest.name == "assistant"
    assert AssistantExtension.manifest.version == "0.1.0"


def test_tools_exist():
    ext = AssistantExtension()
    names = {t.name for t in ext.tools()}
    assert names == {
        "assistant_profile_get",
        "assistant_profile_set",
        "assistant_dialectic_profile_get",
        "assistant_dialectic_profile_update",
        "assistant_dialectic_profile_infer",
        "assistant_plan_validate",
        "assistant_workflow_run",
        "assistant_meeting_prep",
        "assistant_subagent_run",
        "assistant_subagent_parallel",
        "assistant_routine_manage",
        "assistant_routine_run_due",
        "assistant_session_search",
        "assistant_session_recall",
        "assistant_web_rank",
        "assistant_workflow_status",
        "assistant_workflow_list",
        "assistant_memory_add",
        "assistant_memory_search",
        "assistant_skill_manage",
        "assistant_checkpoint_create",
        "assistant_insights",
    }


def test_profile_roundtrip(tmp_path):
    ext = AssistantExtension()
    ext.on_load(_ctx_with_workspace(str(tmp_path)))

    out = ext._handle_profile_set(
        name="Dat",
        goals_json='["ship fast"]',
        preferences_json='{"tone":"concise"}',
        boundaries_json='["no destructive shell"]',
    )
    parsed = json.loads(out)
    assert parsed["ok"] is True
    assert parsed["profile"]["name"] == "Dat"

    out2 = ext._handle_profile_get()
    parsed2 = json.loads(out2)
    assert parsed2["goals"] == ["ship fast"]
    assert parsed2["preferences"]["tone"] == "concise"


def test_dialectic_profile_get_update_infer(tmp_path):
    ext = AssistantExtension()
    ext.on_load(_ctx_with_workspace(str(tmp_path)))

    got = json.loads(ext._handle_dialectic_profile_get())
    assert got["ok"] is True
    assert "dimensions" in got["dialectic_profile"]

    updated = json.loads(
        ext._handle_dialectic_profile_update(
            dimension="speed_vs_quality",
            score=-0.6,
            confidence=0.9,
            rationale="User emphasized quality first.",
            evidence_json='["quality first","careful rollout"]',
        )
    )
    assert updated["ok"] is True
    assert updated["updated"]["key"] == "speed_vs_quality"
    assert updated["updated"]["dimension"]["score"] <= 0

    ext._handle_profile_set(
        goals_json='["ship quickly with quality"]',
        preferences_json='{"tone":"concise","risk":"balanced"}',
        boundaries_json='["require approval for risky changes"]',
    )
    inferred = json.loads(ext._handle_dialectic_profile_infer(query="quality approval concise"))
    assert inferred["ok"] is True
    assert inferred["inference"]["updated"] is True
    dims = inferred["inference"]["profile"]["dimensions"]
    assert "risk_acceptance_vs_safety" in dims


def test_plan_validate_returns_topo_order(tmp_path):
    ext = AssistantExtension()
    ext.on_load(_ctx_with_workspace(str(tmp_path)))

    result = ext._handle_plan_validate(
        objective="release",
        steps_json=(
            '[{"id":"s1","title":"design"},'
            '{"id":"s2","title":"implement","depends_on":["s1"]}]'
        ),
    )
    parsed = json.loads(result)
    assert parsed["ok"] is True
    assert parsed["topo_order"] == ["s1", "s2"]


def test_workflow_run_enqueue_mode(tmp_path):
    ext = AssistantExtension()
    ctx = _ctx_with_workspace(str(tmp_path))
    ext.on_load(ctx)

    result = ext._handle_workflow_run(
        objective="release",
        steps_json=(
            '[{"id":"s1","title":"design"},'
            '{"id":"s2","title":"implement","depends_on":["s1"]}]'
        ),
        execution_mode="enqueue_prompts",
    )
    parsed = json.loads(result)
    assert parsed["ok"] is True
    assert len(parsed["outcomes"]) == 2
    assert ctx.enqueue.called
    assert "handoff" in parsed
    assert "summary_text" in parsed["handoff"]
    assert parsed["handoff"]["summary_text"].startswith("## Active Task")
    assert Path(parsed["handoff_checkpoint"]).is_file()


def test_memory_add_and_search(tmp_path):
    ext = AssistantExtension()
    ext.on_load(_ctx_with_workspace(str(tmp_path)))

    added = ext._handle_memory_add(
        content="Deploy on Fridays after test suite passes.",
        kind="preference",
        source="user",
        confidence=0.92,
        tags_json='["deploy","release"]',
        metadata_json='{"team":"platform"}',
    )
    added_obj = json.loads(added)
    assert added_obj["ok"] is True
    assert added_obj["memory"]["kind"] == "preference"

    searched = ext._handle_memory_search(query="deploy release", limit=3)
    searched_obj = json.loads(searched)
    assert searched_obj["ok"] is True
    assert searched_obj["count"] >= 1
    assert "Deploy on Fridays" in searched_obj["results"][0]["content"]


def test_workflow_run_uses_memory_context(tmp_path):
    ext = AssistantExtension()
    ctx = _ctx_with_workspace(str(tmp_path))
    ext.on_load(ctx)
    ext._handle_memory_add(
        content="For release workflows, prioritize changelog and smoke tests.",
        kind="workflow",
        source="assistant",
    )

    result = ext._handle_workflow_run(
        objective="release",
        steps_json='[{"id":"s1","title":"draft notes"}]',
        execution_mode="enqueue_prompts",
    )
    parsed = json.loads(result)
    assert parsed["ok"] is True
    assert "Relevant memory context" in parsed["memory_context"]
    assert "workflow_id" in parsed["memory_write"]["metadata"]
    assert "Memory index snapshot" in parsed["memory_snapshot"] or parsed["memory_snapshot"] == ""
    assert "## Remaining Work" in parsed["handoff"]["summary_text"]
    assert parsed["handoff_memory_write"]["source"] == "assistant_workflow_handoff"


def test_skill_manage_create_read_list_delete(tmp_path):
    ext = AssistantExtension()
    ext.on_load(_ctx_with_workspace(str(tmp_path)))

    created = json.loads(
        ext._handle_skill_manage(
            action="create",
            name="Release Workflow",
            description="Release execution flow",
            instructions="1. Validate plan\n2. Execute steps",
            tags_json='["release","workflow"]',
        )
    )
    assert created["ok"] is True
    assert created["action"] == "create"
    assert Path(created["skill"]["path"]).is_file()

    listed = json.loads(ext._handle_skill_manage(action="list"))
    assert listed["ok"] is True
    assert listed["count"] >= 1

    read = json.loads(ext._handle_skill_manage(action="read", name="Release Workflow"))
    assert read["ok"] is True
    assert "Release Workflow" in read["skill"]["content"]

    deleted = json.loads(ext._handle_skill_manage(action="delete", name="Release Workflow"))
    assert deleted["ok"] is True
    assert deleted["action"] == "delete"


def test_workflow_run_skill_promotion(tmp_path):
    ext = AssistantExtension()
    ctx = _ctx_with_workspace(str(tmp_path))
    ext.on_load(ctx)

    result = ext._handle_workflow_run(
        objective="release",
        steps_json='[{"id":"s1","title":"draft notes"}]',
        execution_mode="enqueue_prompts",
        promote_to_skill=True,
        skill_name="Release Promotion Skill",
    )
    parsed = json.loads(result)
    assert parsed["ok"] is True
    assert parsed["skill_promotion"] is not None
    assert parsed["skill_promotion"]["slug"] == "release-promotion-skill"
    assert Path(parsed["skill_promotion"]["path"]).is_file()


def test_checkpoint_create_and_insights(tmp_path):
    ext = AssistantExtension()
    ext.on_load(_ctx_with_workspace(str(tmp_path)))

    cp = json.loads(
        ext._handle_checkpoint_create(
            name="sprint-auth-refactor",
            summary="Checkpoint after auth refactor prep",
            metadata_json='{"sprint":"auth"}',
        )
    )
    assert cp["ok"] is True
    assert Path(cp["checkpoint"]).is_file()

    # Create minimal artifacts so insights has non-zero sections.
    ext._handle_memory_add(content="Remember auth release gate.", kind="project", source="assistant")
    ext._handle_skill_manage(
        action="create",
        name="Auth Workflow",
        description="Auth-related flow",
        instructions="1. Gather requirements\n2. Validate constraints",
    )

    report = json.loads(ext._handle_insights())
    assert report["ok"] is True
    summary = report["insights"]["summary"]
    assert summary["checkpoints_total"] >= 1
    assert summary["named_checkpoints_total"] >= 1
    assert summary["skills_total"] >= 1


def test_workflow_run_execute_connector_action(tmp_path):
    ext = AssistantExtension()
    ext.on_load(_ctx_with_workspace(str(tmp_path)))

    result = ext._handle_workflow_run(
        objective="post status",
        steps_json=(
            '[{"id":"s1","title":"notify","action":"connector_action",'
            '"connector":"chat","connector_action":"post_message",'
            '"payload":{"channel":"ops","text":"hello"},"on_failure":"stop"}]'
        ),
        execution_mode="execute",
        policy_profile="dev",
    )
    parsed = json.loads(result)
    assert parsed["ok"] is True
    assert parsed["run_status"] == "completed"
    assert len(parsed["outcomes"]) == 1
    assert parsed["outcomes"][0]["status"] == "completed"


def test_workflow_run_execute_policy_requires_approval(tmp_path):
    ext = AssistantExtension()
    ext.on_load(_ctx_with_workspace(str(tmp_path)))

    result = ext._handle_workflow_run(
        objective="post status",
        steps_json=(
            '[{"id":"s1","title":"notify","action":"connector_action",'
            '"connector":"chat","connector_action":"post_message",'
            '"payload":{"channel":"ops","text":"hello"},"on_failure":"stop"}]'
        ),
        execution_mode="execute",
        policy_profile="balanced",
        approved_risky_actions=False,
    )
    parsed = json.loads(result)
    assert parsed["ok"] is True
    assert parsed["run_status"] == "stopped_on_failure"
    assert parsed["outcomes"][0]["status"] == "failed"
    assert "Approval required by balanced policy" in parsed["outcomes"][0]["error"]


def test_workflow_run_execute_resume_from_state(tmp_path):
    ext = AssistantExtension()
    ext.on_load(_ctx_with_workspace(str(tmp_path)))

    first = json.loads(
        ext._handle_workflow_run(
            objective="resume demo",
            workflow_id="wf-resume-demo",
            steps_json=(
                '['
                '{"id":"s1","title":"start","action":"noop"},'
                '{"id":"s2","title":"failing note read","depends_on":["s1"],'
                '"action":"connector_action","connector":"note","connector_action":"get_note",'
                '"payload":{"id":"missing"},"on_failure":"stop"}'
                ']'
            ),
            execution_mode="execute",
            policy_profile="dev",
        )
    )
    assert first["run_status"] == "stopped_on_failure"
    assert any(x["step_id"] == "s1" and x["status"] == "completed" for x in first["outcomes"])
    assert any(x["step_id"] == "s2" and x["status"] == "failed" for x in first["outcomes"])

    resumed = json.loads(
        ext._handle_workflow_run(
            objective="resume demo",
            workflow_id="wf-resume-demo",
            steps_json=(
                '['
                '{"id":"s1","title":"start","action":"noop"},'
                '{"id":"s2","title":"recovered","depends_on":["s1"],"action":"noop"}'
                ']'
            ),
            execution_mode="execute",
            resume=True,
            policy_profile="dev",
        )
    )
    assert resumed["run_status"] == "completed"
    s1_completed = [x for x in resumed["outcomes"] if x["step_id"] == "s1" and x["status"] == "completed"]
    assert len(s1_completed) == 1
    assert any(x["step_id"] == "s2" and x["status"] == "completed" for x in resumed["outcomes"])


def test_workflow_status_and_list(tmp_path):
    ext = AssistantExtension()
    ext.on_load(_ctx_with_workspace(str(tmp_path)))

    # Seed one completed workflow state.
    run = json.loads(
        ext._handle_workflow_run(
            objective="status list demo",
            workflow_id="wf-status-demo",
            steps_json='[{"id":"s1","title":"only","action":"noop"}]',
            execution_mode="execute",
            policy_profile="dev",
        )
    )
    assert run["run_status"] == "completed"

    status = json.loads(ext._handle_workflow_status("wf-status-demo"))
    assert status["ok"] is True
    wf = status["workflow"]
    assert wf["workflow_id"] == "wf-status-demo"
    assert wf["status"] == "completed"
    assert wf["outcome_count"] >= 1
    assert "s1" in wf["latest_by_step"]

    listed = json.loads(ext._handle_workflow_list(limit=5))
    assert listed["ok"] is True
    assert listed["count"] >= 1
    assert any(x["workflow_id"] == "wf-status-demo" for x in listed["workflows"])


def test_web_rank_normalizes_and_prioritizes_trusted_sources(tmp_path):
    ext = AssistantExtension()
    ext.on_load(_ctx_with_workspace(str(tmp_path)))

    result = json.loads(
        ext._handle_web_rank(
            query="python packaging best practices",
            results_json=(
                '[{"title":"Unknown","url":"https://unknown.example.com/path?utm_source=x","snippet":"packaging guide"},'
                '{"title":"PyPA","url":"https://packaging.python.org/en/latest/?ref=abc","snippet":"official docs"}]'
            ),
            max_results=5,
        )
    )
    assert result["ok"] is True
    assert result["count"] == 2
    assert result["results"][0]["domain"] == "packaging.python.org"
    assert result["results"][0]["url"] == "https://packaging.python.org/en/latest/"
    assert result["results"][0]["trust_tier"] == "high"


def test_session_search_and_recall(tmp_path):
    ext = AssistantExtension()
    ext.on_load(_ctx_with_workspace(str(tmp_path)))

    sessions_dir = tmp_path / ".tau" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    (sessions_dir / "sess-alpha-123.json").write_text(
        json.dumps(
            {
                "id": "sess-alpha-123",
                "name": "Release planning",
                "updated_at": "2026-04-18T08:00:00+00:00",
                "config": {"provider": "openai", "model": "gpt-4o"},
                "messages": [
                    {"role": "user", "content": "How should we do python packaging release notes?"},
                    {"role": "assistant", "content": "Use packaging.python.org guidance first."},
                ],
            }
        ),
        encoding="utf-8",
    )
    (sessions_dir / "sess-beta-456.json").write_text(
        json.dumps(
            {
                "id": "sess-beta-456",
                "name": "Random chat",
                "updated_at": "2026-04-18T07:00:00+00:00",
                "config": {"provider": "openai", "model": "gpt-4o-mini"},
                "messages": [
                    {"role": "user", "content": "Weekend trip ideas"},
                    {"role": "assistant", "content": "Maybe beach and food tour."},
                ],
            }
        ),
        encoding="utf-8",
    )

    searched = json.loads(ext._handle_session_search(query="python packaging", limit=5))
    assert searched["ok"] is True
    assert searched["count"] >= 1
    assert searched["sessions"][0]["session_id"] == "sess-alpha-123"

    recalled = json.loads(
        ext._handle_session_recall(
            session_id="sess-alpha",
            query="packaging",
            max_points=4,
        )
    )
    assert recalled["ok"] is True
    assert recalled["session"]["session_id"] == "sess-alpha-123"
    assert "Focus: packaging" in recalled["session"]["summary_text"]


def test_workflow_auto_skill_learning_create_then_improve(tmp_path):
    ext = AssistantExtension()
    ext.on_load(_ctx_with_workspace(str(tmp_path)))

    created = json.loads(
        ext._handle_workflow_run(
            objective="release coordination",
            workflow_id="wf-auto-learn-1",
            steps_json=(
                '[{"id":"s1","title":"draft plan","action":"noop"},'
                '{"id":"s2","title":"review plan","depends_on":["s1"],"action":"noop"}]'
            ),
            execution_mode="execute",
            policy_profile="dev",
            auto_learn_skill=True,
            auto_learn_min_completed_steps=2,
            skill_name="Release Coordination Skill",
        )
    )
    assert created["ok"] is True
    assert created["skill_auto_learning"] is not None
    assert created["skill_auto_learning"]["triggered"] is True
    assert created["skill_auto_learning"]["mode"] == "created"
    skill_path = Path(created["skill_auto_learning"]["skill"]["path"])
    assert skill_path.is_file()

    improved = json.loads(
        ext._handle_workflow_run(
            objective="release coordination",
            workflow_id="wf-auto-learn-2",
            steps_json=(
                '[{"id":"s1","title":"draft plan","action":"noop"},'
                '{"id":"s2","title":"execute release","depends_on":["s1"],"action":"noop"}]'
            ),
            execution_mode="execute",
            policy_profile="dev",
            auto_learn_skill=True,
            auto_learn_min_completed_steps=2,
            skill_name="Release Coordination Skill",
        )
    )
    assert improved["ok"] is True
    assert improved["skill_auto_learning"] is not None
    assert improved["skill_auto_learning"]["triggered"] is True
    assert improved["skill_auto_learning"]["mode"] == "improved"
    body = skill_path.read_text(encoding="utf-8")
    assert "## Continuous Improvements" in body


def test_workflow_auto_skill_learning_skips_when_too_few_steps(tmp_path):
    ext = AssistantExtension()
    ext.on_load(_ctx_with_workspace(str(tmp_path)))

    result = json.loads(
        ext._handle_workflow_run(
            objective="tiny task",
            workflow_id="wf-auto-learn-skip",
            steps_json='[{"id":"s1","title":"only one step","action":"noop"}]',
            execution_mode="execute",
            policy_profile="dev",
            auto_learn_skill=True,
            auto_learn_min_completed_steps=2,
        )
    )
    assert result["ok"] is True
    assert result["skill_auto_learning"] is not None
    assert result["skill_auto_learning"]["triggered"] is False
    assert result["skill_auto_learning"]["reason"] == "not_enough_completed_steps"


def test_routine_manage_and_run_due_delivery(tmp_path):
    ext = AssistantExtension()
    ext.on_load(_ctx_with_workspace(str(tmp_path)))

    created = json.loads(
        ext._handle_routine_manage(
            action="create",
            routine_id="r1",
            title="daily status",
            interval_minutes=60,
            delivery_connector="chat",
            delivery_target="team-ops",
            delivery_template="Routine {routine_title} due at {timestamp}",
        )
    )
    assert created["ok"] is True
    assert created["routine"]["id"] == "r1"

    ran = json.loads(ext._handle_routine_run_due(limit=5))
    assert ran["ok"] is True
    assert ran["delivered_count"] == 1
    assert ran["failed_count"] == 0
    assert ran["deliveries"][0]["connector"] == "chat"
    assert ran["deliveries"][0]["payload"]["channel"] == "team-ops"

    listed = json.loads(ext._handle_routine_manage(action="list"))
    assert listed["ok"] is True
    assert listed["count"] >= 1
    row = next(x for x in listed["routines"] if x["id"] == "r1")
    assert row["last_run"] is not None


def test_routine_run_due_failure_does_not_mark_run(tmp_path):
    ext = AssistantExtension()
    ext.on_load(_ctx_with_workspace(str(tmp_path)))

    json.loads(
        ext._handle_routine_manage(
            action="create",
            routine_id="r2",
            title="broken delivery",
            interval_minutes=60,
            delivery_connector="email",
            delivery_target="",
        )
    )
    ran = json.loads(ext._handle_routine_run_due(limit=5))
    assert ran["ok"] is True
    assert ran["delivered_count"] == 0
    assert ran["failed_count"] == 1
    assert ran["failures"][0]["routine_id"] == "r2"

    listed = json.loads(ext._handle_routine_manage(action="list"))
    row = next(x for x in listed["routines"] if x["id"] == "r2")
    assert row["last_run"] is None


def test_subagent_run_single(tmp_path):
    ext = AssistantExtension()
    ctx = _ctx_with_workspace(str(tmp_path))
    ext.on_load(ctx)

    from tau.core.types import TextDelta

    ctx.create_sub_session = MagicMock(
        return_value=_FakeSubSession([TextDelta(text="analysis complete")])
    )
    result = json.loads(
        ext._handle_subagent_run(
            task="find release risks",
            persona="",
            max_turns=4,
        )
    )
    assert result["ok"] is True
    assert "analysis complete" in result["result"]


def test_subagent_parallel(tmp_path):
    ext = AssistantExtension()
    ctx = _ctx_with_workspace(str(tmp_path))
    ext.on_load(ctx)

    from tau.core.types import TextDelta

    # Return deterministic short output for each spawned sub-session.
    ctx.create_sub_session = MagicMock(
        return_value=_FakeSubSession([TextDelta(text="done")])
    )
    result = json.loads(
        ext._handle_subagent_parallel(
            tasks_json='[{"id":"t1","task":"scan code"},{"id":"t2","task":"verify tests"}]',
            max_workers=2,
        )
    )
    assert result["ok"] is True
    assert result["count"] == 2
    assert result["completed"] == 2
    assert result["failed"] == 0
