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
