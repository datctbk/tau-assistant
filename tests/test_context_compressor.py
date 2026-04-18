from __future__ import annotations

from context_compressor import WorkflowContextCompressor
from planner import PlanStep, WorkflowPlan


def test_workflow_context_compressor_builds_handoff_sections():
    engine = WorkflowContextCompressor(max_handoff_chars=2400)
    plan = WorkflowPlan(
        id="wf-1",
        objective="release",
        steps=[
            PlanStep(id="s1", title="draft notes"),
            PlanStep(id="s2", title="run smoke tests", depends_on=["s1"]),
        ],
    )
    handoff = engine.build_workflow_handoff(
        objective="release",
        plan=plan,
        outcomes=[{"step_id": "s1", "status": "completed", "checkpoint": "/tmp/cp.json"}],
        memory_context="Relevant memory context:\n- [project/local] Release checklist.",
        memory_snapshot="Memory index snapshot:\n- Local index:\n- [Release](project.md) — project",
    )

    text = handoff["summary_text"]
    assert "## Active Task" in text
    assert "## Completed" in text
    assert "## Remaining Work" in text
    assert "## Decisions" in text
    assert "## Risks" in text
    assert "## Next Actions" in text
    assert "run smoke tests" in text
