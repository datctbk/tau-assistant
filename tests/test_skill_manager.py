from __future__ import annotations

from pathlib import Path

from skill_manager import SkillManager


def test_skill_manager_promote_from_workflow(tmp_path):
    mgr = SkillManager(str(tmp_path))
    promoted = mgr.promote_from_workflow(
        skill_name="Release Handoff",
        objective="release",
        workflow_id="wf-123",
        handoff={
            "completed_steps": ["draft notes"],
            "decisions": ["Run in dependency order."],
            "next_actions": ["Resume from: smoke tests"],
            "summary_text": "## Active Task\n- release",
        },
        outcomes=[{"step_id": "s1", "status": "completed"}],
    )
    assert promoted["slug"] == "release-handoff"
    assert promoted["workflow_id"] == "wf-123"
    assert Path(promoted["path"]).is_file()
    text = Path(promoted["path"]).read_text(encoding="utf-8")
    assert "source" in text
    assert "workflow_promotion" in text
    assert "## Procedure" in text


def test_skill_manager_auto_learn_create_then_improve(tmp_path):
    mgr = SkillManager(str(tmp_path))
    created = mgr.auto_learn_from_workflow(
        objective="release",
        workflow_id="wf-1",
        handoff={
            "completed_steps": ["draft notes", "run smoke tests"],
            "decisions": ["Keep topological order."],
            "next_actions": ["Publish release notes"],
            "summary_text": "## Active Task\n- release",
        },
        outcomes=[
            {"step_id": "s1", "status": "completed"},
            {"step_id": "s2", "status": "completed"},
        ],
        skill_name="Release Auto Skill",
        min_completed_steps=2,
    )
    assert created["triggered"] is True
    assert created["mode"] == "created"

    improved = mgr.auto_learn_from_workflow(
        objective="release",
        workflow_id="wf-2",
        handoff={
            "completed_steps": ["publish notes"],
            "decisions": ["Keep rollback plan."],
            "next_actions": ["Notify channel"],
            "summary_text": "## Active Task\n- release",
        },
        outcomes=[
            {"step_id": "s1", "status": "completed"},
            {"step_id": "s2", "status": "completed"},
        ],
        skill_name="Release Auto Skill",
        min_completed_steps=2,
    )
    assert improved["triggered"] is True
    assert improved["mode"] == "improved"
    text = Path(improved["skill"]["path"]).read_text(encoding="utf-8")
    assert "## Continuous Improvements" in text


def test_skill_manager_auto_learn_skips_low_signal(tmp_path):
    mgr = SkillManager(str(tmp_path))
    skipped = mgr.auto_learn_from_workflow(
        objective="tiny",
        workflow_id="wf-skip",
        handoff={"summary_text": "tiny"},
        outcomes=[{"step_id": "s1", "status": "completed"}],
        min_completed_steps=2,
    )
    assert skipped["triggered"] is False
    assert skipped["reason"] == "not_enough_completed_steps"
