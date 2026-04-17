from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

try:
    from tau.core.assistant_events import append_assistant_event, make_assistant_event
    from tau.core.audit import append_audit_record
except Exception:  # noqa: BLE001
    def append_audit_record(workspace_root: str, event_type: str, payload: dict) -> str:
        root = Path(workspace_root) / ".tau" / "audit"
        root.mkdir(parents=True, exist_ok=True)
        target = root / "assistant-actions.jsonl"
        rec = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "payload": payload,
        }
        with target.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return str(target)

    def make_assistant_event(*, family: str, name: str, payload: dict, session_id: str = "", severity: str = "info") -> dict:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "family": family,
            "name": name,
            "payload": payload,
            "session_id": session_id,
            "severity": severity,
        }

    def append_assistant_event(workspace_root: str, event: dict) -> str:
        root = Path(workspace_root) / ".tau" / "events"
        root.mkdir(parents=True, exist_ok=True)
        target = root / "assistant-events.jsonl"
        with target.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        return str(target)

from planner import WorkflowPlan


class WorkflowRunner:
    """Executes dependency-ordered plans with checkpoint-on-step-complete."""

    def __init__(self, workspace_root: str, session_id: str = "") -> None:
        self.workspace_root = workspace_root
        self.session_id = session_id

    def _checkpoint_dir(self) -> Path:
        p = Path(self.workspace_root) / ".tau" / "checkpoints"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _write_step_checkpoint(self, workflow_id: str, step_id: str, status: str, result: str) -> Path:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        fp = self._checkpoint_dir() / f"{ts}_{workflow_id}_{step_id}.json"
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "workflow_id": workflow_id,
            "step_id": step_id,
            "status": status,
            "result": result[:500],
        }
        fp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return fp

    def run(self, plan: WorkflowPlan, execute_step: Callable[[str], str]) -> list[dict[str, str]]:
        order = plan.topo_order()
        outcomes: list[dict[str, str]] = []

        for sid in order:
            append_assistant_event(
                self.workspace_root,
                make_assistant_event(
                    family="workflow",
                    name="step_started",
                    payload={"workflow_id": plan.id, "step_id": sid},
                    session_id=self.session_id,
                ),
            )

            result = execute_step(sid)
            cp = self._write_step_checkpoint(plan.id, sid, "completed", result)

            append_audit_record(
                self.workspace_root,
                "workflow.step_completed",
                {"workflow_id": plan.id, "step_id": sid, "checkpoint": str(cp)},
            )
            append_assistant_event(
                self.workspace_root,
                make_assistant_event(
                    family="workflow",
                    name="step_completed",
                    payload={
                        "workflow_id": plan.id,
                        "step_id": sid,
                        "checkpoint": str(cp),
                    },
                    session_id=self.session_id,
                ),
            )

            outcomes.append({"step_id": sid, "status": "completed", "checkpoint": str(cp)})

        return outcomes
