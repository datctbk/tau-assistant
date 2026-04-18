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
        "assistant_plan_validate",
        "assistant_workflow_run",
        "assistant_meeting_prep",
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
