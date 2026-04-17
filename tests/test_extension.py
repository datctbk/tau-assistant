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
