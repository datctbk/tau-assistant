from __future__ import annotations

import importlib.util
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from routine_engine import RoutineEngine


class AssistantInsightsEngine:
    """Filesystem-based assistant insights for workflows, memory, skills, and checkpoints."""

    def __init__(self, workspace_root: str) -> None:
        self.workspace_root = workspace_root
        self.root = Path(workspace_root)

    def _checkpoint_files(self) -> list[Path]:
        p = self.root / ".tau" / "checkpoints"
        if not p.exists():
            return []
        return sorted([x for x in p.iterdir() if x.is_file()], key=lambda x: x.stat().st_mtime, reverse=True)

    def _skill_files(self) -> list[Path]:
        p = self.root / ".tau" / "assistant" / "skills"
        if not p.exists():
            return []
        return sorted(p.glob("*/SKILL.md"), key=lambda x: x.stat().st_mtime, reverse=True)

    def _memory_stats(self) -> dict[str, Any]:
        try:
            ext_path = self.root.parent / "tau-memory" / "extensions" / "memory" / "extension.py"
            if not ext_path.exists():
                return {"topics_total": 0, "entries_estimated": 0}
            mod_name = "_tau_memory_ext_for_insights"
            spec = importlib.util.spec_from_file_location(mod_name, str(ext_path))
            if spec is None or spec.loader is None:
                return {"topics_total": 0, "entries_estimated": 0}
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            store = module.MemoryStore(self.workspace_root)
            topics = store.list_topics()
            entries = 0
            for t in topics:
                name = str(t.get("name", "")).strip()
                scope = str(t.get("scope", "local"))
                if not name or name.lower() == "memory":
                    continue
                text = store.read_topic(name=name, scope=scope)
                entries += max(0, len(re.findall(r"^##\s+", text, flags=re.M)))
            return {"topics_total": len(topics), "entries_estimated": entries}
        except Exception:
            return {"topics_total": 0, "entries_estimated": 0}

    def _audit_stats(self) -> dict[str, Any]:
        audit_path = self.root / ".tau" / "audit" / "assistant-actions.jsonl"
        if not audit_path.exists():
            return {"events_total": 0, "workflow_steps_completed": 0, "named_checkpoints": 0}
        total = 0
        step_completed = 0
        named_checkpoints = 0
        with audit_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                total += 1
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                et = str(row.get("event_type", ""))
                if et == "workflow.step_completed":
                    step_completed += 1
                if et == "assistant.checkpoint_created":
                    named_checkpoints += 1
        return {
            "events_total": total,
            "workflow_steps_completed": step_completed,
            "named_checkpoints": named_checkpoints,
        }

    def generate(self) -> dict[str, Any]:
        checkpoints = self._checkpoint_files()
        skills = self._skill_files()
        memory = self._memory_stats()
        audit = self._audit_stats()
        routines = RoutineEngine.load_workspace(self.workspace_root)

        named_cp = [x for x in checkpoints if "_named_" in x.name]
        workflow_step_cp = [x for x in checkpoints if x.suffix == ".json" and "_named_" not in x.name]
        handoff_cp = [x for x in checkpoints if x.name.endswith("_handoff.md")]

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "workspace_root": self.workspace_root,
            "summary": {
                "checkpoints_total": len(checkpoints),
                "named_checkpoints_total": len(named_cp),
                "workflow_step_checkpoints_total": len(workflow_step_cp),
                "handoff_checkpoints_total": len(handoff_cp),
                "skills_total": len(skills),
                "routines_total": len(routines.routines),
                "memory_topics_total": memory["topics_total"],
                "memory_entries_estimated": memory["entries_estimated"],
                "audit_events_total": audit["events_total"],
                "workflow_steps_completed": audit["workflow_steps_completed"],
            },
            "recent": {
                "checkpoints": [str(x) for x in checkpoints[:5]],
                "skills": [str(x) for x in skills[:5]],
            },
        }
