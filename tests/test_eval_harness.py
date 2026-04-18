from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import importlib.util


ROOT = Path(__file__).resolve().parent.parent
TAU_ROOT = ROOT.parent / "tau"
sys.path.insert(0, str(TAU_ROOT))

_mod_name = "_tau_ext_assistant_ext_eval"
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


def test_eval_harness_memory_handoff_skill_persistence_and_web_ranking(tmp_path):
    ext = AssistantExtension()
    ext.on_load(_ctx_with_workspace(str(tmp_path)))

    mem = json.loads(
        ext._handle_memory_add(
            content="Use official docs first for Python packaging guidance.",
            kind="preference",
            source="eval-harness",
            confidence=0.9,
            tags_json='["web","trust"]',
        )
    )
    assert mem["ok"] is True

    run = json.loads(
        ext._handle_workflow_run(
            objective="prepare packaging recommendations",
            workflow_id="wf-eval-1",
            steps_json='[{"id":"s1","title":"collect sources","action":"noop"}]',
            execution_mode="execute",
            policy_profile="dev",
            promote_to_skill=True,
            skill_name="Packaging Recommendations Flow",
        )
    )
    assert run["ok"] is True
    assert run["run_status"] == "completed"
    assert run["handoff"]["summary_text"].startswith("## Active Task")
    assert run["skill_promotion"] is not None

    status = json.loads(ext._handle_workflow_status("wf-eval-1"))
    assert status["ok"] is True
    assert status["workflow"]["status"] == "completed"

    listing = json.loads(ext._handle_workflow_list(limit=10))
    assert listing["ok"] is True
    assert any(w["workflow_id"] == "wf-eval-1" for w in listing["workflows"])

    ranked = json.loads(
        ext._handle_web_rank(
            query="python packaging best practices",
            results_json=(
                '['
                '{"title":"Blog post","url":"https://unknown.example.com/pypkg?utm_source=x","snippet":"packaging tips"},'
                '{"title":"PyPA docs","url":"https://packaging.python.org/en/latest/?ref=abc","snippet":"official packaging docs"}'
                ']'
            ),
            max_results=5,
        )
    )
    assert ranked["ok"] is True
    assert ranked["count"] == 2
    assert ranked["results"][0]["domain"] == "packaging.python.org"
    assert ranked["results"][0]["trust_tier"] == "high"
    assert "ranking_reason" in ranked["results"][0]

