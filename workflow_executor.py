from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from connector_router import ConnectorRouter
from memory_manager import MemoryManager
from planner import PlanStep


class WorkflowExecutor:
    """Executes individual workflow steps in real execution mode."""

    def __init__(
        self,
        *,
        workspace_root: str,
        memory: MemoryManager,
        router: ConnectorRouter,
        ext_context: Any = None,
    ) -> None:
        self.workspace_root = workspace_root
        self.memory = memory
        self.router = router
        self.ext_context = ext_context

    def execute_step(self, step: PlanStep, *, mode: str, execution_brief: str) -> str:
        action = (step.action or "noop").strip().lower()
        if mode == "enqueue_prompts":
            if self.ext_context is not None:
                self.ext_context.enqueue(
                    (
                        f"[assistant workflow] Execute step {step.id} ({step.title}).\n\n"
                        f"{execution_brief}"
                    )
                )
            return f"enqueued prompt for step {step.id}"

        if mode == "dry_run":
            return f"dry run completed step {step.id}"

        if action in {"", "noop"}:
            return f"executed noop step {step.id}: {step.title}"

        if action == "connector_action":
            connector = (step.connector or "").strip()
            connector_action = (step.connector_action or "").strip()
            if not connector:
                raise ValueError(f"Step {step.id}: connector is required for connector_action")
            if not connector_action:
                raise ValueError(f"Step {step.id}: connector_action is required")
            resp = self.router.route(connector, connector_action, step.payload or {})
            if not resp.ok:
                raise ValueError(f"Step {step.id}: {connector}.{connector_action} failed: {resp.error}")
            return f"connector action ok: {connector}.{connector_action}"

        if action == "memory_add":
            content = str((step.payload or {}).get("content", "")).strip()
            if not content:
                raise ValueError(f"Step {step.id}: payload.content is required for memory_add")
            kind = str((step.payload or {}).get("kind", "project"))
            source = str((step.payload or {}).get("source", "workflow"))
            self.memory.add_memory(content=content, kind=kind, source=source, confidence=0.85)
            return f"memory added for step {step.id}"

        if action == "run_bash":
            command = str((step.payload or {}).get("command", "")).strip()
            if not command:
                raise ValueError(f"Step {step.id}: payload.command is required for run_bash")
            proc = subprocess.run(
                command,
                shell=True,
                cwd=str(Path(self.workspace_root)),
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                stderr = (proc.stderr or "").strip()
                raise ValueError(
                    f"Step {step.id}: bash command failed (code={proc.returncode}): {stderr[:300]}"
                )
            return f"bash ok for step {step.id}: {(proc.stdout or '').strip()[:200]}"

        raise ValueError(f"Step {step.id}: unsupported action {action!r}")
