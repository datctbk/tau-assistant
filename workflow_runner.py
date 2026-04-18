from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from typing import Any

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
from planner import PlanStep


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

    def write_handoff_checkpoint(self, workflow_id: str, handoff_summary: str) -> Path:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        fp = self._checkpoint_dir() / f"{ts}_{workflow_id}_handoff.md"
        fp.write_text(handoff_summary.strip() + "\n", encoding="utf-8")

        append_audit_record(
            self.workspace_root,
            "workflow.handoff_saved",
            {"workflow_id": workflow_id, "checkpoint": str(fp)},
        )
        append_assistant_event(
            self.workspace_root,
            make_assistant_event(
                family="workflow",
                name="handoff_saved",
                payload={"workflow_id": workflow_id, "checkpoint": str(fp)},
                session_id=self.session_id,
            ),
        )
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

    def _state_file(self, workflow_id: str) -> Path:
        return self._checkpoint_dir() / f"workflow_state_{workflow_id}.json"

    def _load_state(self, workflow_id: str) -> dict:
        fp = self._state_file(workflow_id)
        if not fp.exists():
            return {"workflow_id": workflow_id, "completed": [], "outcomes": []}
        try:
            return json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            return {"workflow_id": workflow_id, "completed": [], "outcomes": []}

    def get_state(self, workflow_id: str) -> dict:
        state = self._load_state(workflow_id)
        outcomes = [x for x in state.get("outcomes", []) if isinstance(x, dict)]
        latest_by_step: dict[str, dict[str, Any]] = {}
        for rec in outcomes:
            step_id = str(rec.get("step_id", "")).strip()
            if not step_id:
                continue
            latest_by_step[step_id] = rec
        failed_steps = [sid for sid, rec in latest_by_step.items() if str(rec.get("status", "")).strip() == "failed"]
        status = "completed"
        if failed_steps:
            status = "needs_attention"
        if not outcomes:
            status = "empty"
        return {
            "workflow_id": workflow_id,
            "state_path": str(self._state_file(workflow_id)),
            "saved_at": str(state.get("saved_at", "")),
            "completed_count": len([x for x in state.get("completed", []) if isinstance(x, str)]),
            "outcome_count": len(outcomes),
            "latest_by_step": latest_by_step,
            "failed_steps": failed_steps,
            "status": status,
        }

    def list_states(self, limit: int = 20) -> list[dict[str, Any]]:
        cap = max(1, int(limit))
        rows: list[dict[str, Any]] = []
        for fp in self._checkpoint_dir().glob("workflow_state_*.json"):
            workflow_id = fp.stem.replace("workflow_state_", "", 1)
            rec = self.get_state(workflow_id)
            rec["state_path"] = str(fp)
            rec["_mtime"] = fp.stat().st_mtime
            rows.append(rec)
        rows.sort(key=lambda x: float(x.get("_mtime", 0)), reverse=True)
        for rec in rows:
            rec.pop("_mtime", None)
        return rows[:cap]

    def _save_state(self, workflow_id: str, *, completed: list[str], outcomes: list[dict[str, Any]]) -> str:
        fp = self._state_file(workflow_id)
        payload = {
            "workflow_id": workflow_id,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "completed": completed,
            "outcomes": outcomes,
        }
        fp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(fp)

    def run_with_recovery(
        self,
        plan: WorkflowPlan,
        execute_step: Callable[[PlanStep], str],
        *,
        resume: bool = False,
    ) -> dict:
        order = plan.topo_order()
        step_map = {s.id: s for s in plan.steps}
        state = self._load_state(plan.id) if resume else {"workflow_id": plan.id, "completed": [], "outcomes": []}
        completed = [str(x) for x in state.get("completed", [])]
        outcomes: list[dict[str, Any]] = [x for x in state.get("outcomes", []) if isinstance(x, dict)]
        completed_set = set(completed)

        for sid in order:
            step = step_map[sid]
            if sid in completed_set:
                continue

            append_assistant_event(
                self.workspace_root,
                make_assistant_event(
                    family="workflow",
                    name="step_started",
                    payload={"workflow_id": plan.id, "step_id": sid},
                    session_id=self.session_id,
                ),
            )

            max_attempts = max(1, int(step.retries) + 1)
            attempt = 0
            last_error = ""
            while attempt < max_attempts:
                attempt += 1
                try:
                    result = execute_step(step)
                    cp = self._write_step_checkpoint(plan.id, sid, "completed", result)
                    rec = {"step_id": sid, "status": "completed", "checkpoint": str(cp), "attempts": attempt}
                    outcomes.append(rec)
                    completed.append(sid)
                    completed_set.add(sid)
                    append_audit_record(
                        self.workspace_root,
                        "workflow.step_completed",
                        {"workflow_id": plan.id, "step_id": sid, "checkpoint": str(cp), "attempts": attempt},
                    )
                    append_assistant_event(
                        self.workspace_root,
                        make_assistant_event(
                            family="workflow",
                            name="step_completed",
                            payload={"workflow_id": plan.id, "step_id": sid, "checkpoint": str(cp), "attempts": attempt},
                            session_id=self.session_id,
                        ),
                    )
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = str(exc)
                    append_assistant_event(
                        self.workspace_root,
                        make_assistant_event(
                            family="workflow",
                            name="step_retry" if attempt < max_attempts else "step_failed",
                            payload={"workflow_id": plan.id, "step_id": sid, "attempt": attempt, "error": last_error},
                            session_id=self.session_id,
                            severity="warning",
                        ),
                    )
                    if attempt >= max_attempts:
                        cp = self._write_step_checkpoint(plan.id, sid, "failed", last_error)
                        outcomes.append(
                            {
                                "step_id": sid,
                                "status": "failed",
                                "checkpoint": str(cp),
                                "attempts": attempt,
                                "error": last_error,
                            }
                        )
                        append_audit_record(
                            self.workspace_root,
                            "workflow.step_failed",
                            {"workflow_id": plan.id, "step_id": sid, "checkpoint": str(cp), "error": last_error},
                        )
                        if (step.on_failure or "stop").strip().lower() != "continue":
                            state_path = self._save_state(plan.id, completed=completed, outcomes=outcomes)
                            return {
                                "workflow_id": plan.id,
                                "status": "stopped_on_failure",
                                "failed_step": sid,
                                "error": last_error,
                                "state_path": state_path,
                                "outcomes": outcomes,
                            }
            self._save_state(plan.id, completed=completed, outcomes=outcomes)

        state_path = self._save_state(plan.id, completed=completed, outcomes=outcomes)
        latest_status_by_step: dict[str, str] = {}
        for rec in outcomes:
            sid = str(rec.get("step_id", "")).strip()
            if not sid:
                continue
            latest_status_by_step[sid] = str(rec.get("status", "")).strip()
        any_failed = any(status == "failed" for status in latest_status_by_step.values())
        return {
            "workflow_id": plan.id,
            "status": "completed_with_failures" if any_failed else "completed",
            "state_path": state_path,
            "outcomes": outcomes,
        }
