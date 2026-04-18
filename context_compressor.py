from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from context_engine import ContextEngine
from planner import WorkflowPlan


class WorkflowContextCompressor(ContextEngine):
    """Deterministic workflow context compressor and handoff builder."""

    def __init__(self, *, max_brief_chars: int = 1400, max_handoff_chars: int = 3200) -> None:
        self.max_brief_chars = max(600, int(max_brief_chars))
        self.max_handoff_chars = max(1200, int(max_handoff_chars))

    def memory_snapshot(self, workspace_root: str) -> str:
        """Read a compact memory index snapshot from tau-memory when available."""
        try:
            root = Path(__file__).resolve().parents[1]
            ext_path = root / "tau-memory" / "extensions" / "memory" / "extension.py"
            if not ext_path.exists():
                return ""
            mod_name = "_tau_memory_ext_for_context_compressor"
            spec = importlib.util.spec_from_file_location(mod_name, str(ext_path))
            if spec is None or spec.loader is None:
                return ""
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            store = module.MemoryStore(workspace_root)
            local = store.read_entrypoint(scope="local").strip()
            global_ = store.read_entrypoint(scope="global").strip()
            if not local and not global_:
                return ""
            return (
                "Memory index snapshot:\n"
                f"- Local index:\n{local or '(empty)'}\n\n"
                f"- Global index:\n{global_ or '(empty)'}"
            ).strip()
        except Exception:
            return ""

    @staticmethod
    def _clip(text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        if max_chars <= 3:
            return text[:max_chars]
        return text[: max_chars - 3].rstrip() + "..."

    @staticmethod
    def _step_title(plan: WorkflowPlan, step_id: str) -> str:
        for s in plan.steps:
            if s.id == step_id:
                return s.title
        return step_id

    def build_execution_brief(
        self,
        *,
        objective: str,
        plan: WorkflowPlan,
        memory_context: str = "",
        memory_snapshot: str = "",
    ) -> str:
        order = plan.topo_order()
        head = (
            "Workflow Brief\n"
            f"Objective: {objective}\n"
            f"Workflow ID: {plan.id}\n"
            f"Dependency order: {', '.join(order)}"
        )
        body_parts = [head]
        if memory_context.strip():
            body_parts.append(f"Relevant memory:\n{memory_context.strip()}")
        if memory_snapshot.strip():
            body_parts.append(f"Memory snapshot:\n{memory_snapshot.strip()}")
        brief = "\n\n".join(body_parts)
        return self._clip(brief, self.max_brief_chars)

    def build_workflow_handoff(
        self,
        *,
        objective: str,
        plan: WorkflowPlan,
        outcomes: list[dict[str, str]],
        memory_context: str = "",
        memory_snapshot: str = "",
    ) -> dict[str, Any]:
        order = plan.topo_order()
        completed_ids = [x.get("step_id", "") for x in outcomes if x.get("status") == "completed"]
        completed_set = {x for x in completed_ids if x}
        remaining_ids = [sid for sid in order if sid not in completed_set]

        completed_titles = [self._step_title(plan, sid) for sid in completed_ids if sid]
        remaining_titles = [self._step_title(plan, sid) for sid in remaining_ids]

        decisions = [
            f"Executed {len(completed_set)}/{len(order)} planned steps in dependency order.",
            f"Execution mode should persist from caller context (workflow_id={plan.id}).",
        ]
        risks = (
            [f"Incomplete steps remain: {', '.join(remaining_titles)}"]
            if remaining_titles
            else ["No incomplete workflow steps were recorded."]
        )
        next_actions = (
            [f"Resume from: {remaining_titles[0]}"] if remaining_titles else ["Validate outputs and close workflow."]
        )

        completed_lines = [f"- {title}" for title in completed_titles] if completed_titles else ["- (none)"]
        remaining_lines = [f"- {title}" for title in remaining_titles] if remaining_titles else ["- (none)"]
        decision_lines = [f"- {line}" for line in decisions]
        risk_lines = [f"- {line}" for line in risks]
        next_action_lines = [f"- {line}" for line in next_actions]

        text_parts = [
            "## Active Task",
            f"- {objective}",
            "",
            "## Completed",
            *completed_lines,
            "",
            "## Remaining Work",
            *remaining_lines,
            "",
            "## Decisions",
            *decision_lines,
            "",
            "## Risks",
            *risk_lines,
            "",
            "## Next Actions",
            *next_action_lines,
        ]

        if memory_context.strip():
            text_parts.extend(["", "## Relevant Memory", self._clip(memory_context.strip(), 900)])
        if memory_snapshot.strip():
            text_parts.extend(["", "## Memory Snapshot", self._clip(memory_snapshot.strip(), 900)])

        summary_text = self._clip("\n".join(text_parts).strip(), self.max_handoff_chars)

        return {
            "objective": objective,
            "workflow_id": plan.id,
            "completed_steps": completed_titles,
            "remaining_steps": remaining_titles,
            "decisions": decisions,
            "risks": risks,
            "next_actions": next_actions,
            "summary_text": summary_text,
        }
