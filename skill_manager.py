from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return cleaned or "skill"


class SkillManager:
    """File-based assistant skills under .tau/assistant/skills."""

    def __init__(self, workspace_root: str) -> None:
        self.workspace_root = workspace_root

    @property
    def root(self) -> Path:
        return Path(self.workspace_root) / ".tau" / "assistant" / "skills"

    def _skill_dir(self, name: str) -> Path:
        return self.root / _slugify(name)

    def _skill_file(self, name: str) -> Path:
        return self._skill_dir(name) / "SKILL.md"

    @staticmethod
    def _clip(text: str, limit: int = 1200) -> str:
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 3)].rstrip() + "..."

    def _render_skill_markdown(
        self,
        *,
        name: str,
        description: str,
        instructions: str,
        tags: list[str] | None = None,
        source: str = "manual",
        workflow_id: str = "",
    ) -> str:
        uniq_tags = [str(t).strip() for t in (tags or []) if str(t).strip()]
        payload = {
            "name": name.strip(),
            "description": description.strip(),
            "tags": uniq_tags,
            "source": source,
            "workflow_id": workflow_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        fm = json.dumps(payload, ensure_ascii=False, indent=2)
        return f"---\n{fm}\n---\n\n{instructions.strip()}\n"

    def create_or_update(
        self,
        *,
        name: str,
        description: str,
        instructions: str,
        tags: list[str] | None = None,
        source: str = "manual",
        workflow_id: str = "",
    ) -> dict[str, Any]:
        if not name.strip():
            raise ValueError("name is required")
        if not description.strip():
            raise ValueError("description is required")
        if not instructions.strip():
            raise ValueError("instructions is required")

        target_dir = self._skill_dir(name)
        target_file = self._skill_file(name)
        target_dir.mkdir(parents=True, exist_ok=True)
        content = self._render_skill_markdown(
            name=name,
            description=description,
            instructions=instructions,
            tags=tags,
            source=source,
            workflow_id=workflow_id,
        )
        target_file.write_text(content, encoding="utf-8")
        return {
            "name": name.strip(),
            "slug": target_dir.name,
            "path": str(target_file),
            "description": description.strip(),
            "tags": [str(t).strip() for t in (tags or []) if str(t).strip()],
            "source": source,
            "workflow_id": workflow_id,
        }

    def read(self, *, name: str) -> dict[str, Any]:
        target = self._skill_file(name)
        if not target.exists():
            raise ValueError(f"Skill not found: {name}")
        raw = target.read_text(encoding="utf-8")
        return {
            "name": name.strip(),
            "slug": self._skill_dir(name).name,
            "path": str(target),
            "content": raw,
        }

    def delete(self, *, name: str) -> dict[str, Any]:
        target = self._skill_file(name)
        if not target.exists():
            raise ValueError(f"Skill not found: {name}")
        target.unlink()
        parent = target.parent
        try:
            parent.rmdir()
        except OSError:
            pass
        return {"ok": True, "name": name.strip(), "slug": self._skill_dir(name).name}

    def list(self) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        rows: list[dict[str, Any]] = []
        for p in sorted(self.root.glob("*/SKILL.md")):
            rows.append(
                {
                    "slug": p.parent.name,
                    "path": str(p),
                    "size_bytes": p.stat().st_size,
                    "modified": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
                }
            )
        return rows

    def promote_from_workflow(
        self,
        *,
        skill_name: str,
        objective: str,
        workflow_id: str,
        handoff: dict[str, Any],
        outcomes: list[dict[str, str]],
    ) -> dict[str, Any]:
        completed_steps = handoff.get("completed_steps", [])
        decisions = handoff.get("decisions", [])
        next_actions = handoff.get("next_actions", [])
        summary_text = str(handoff.get("summary_text", "")).strip()

        step_lines = "\n".join(f"- {s}" for s in completed_steps) if completed_steps else "- (none recorded)"
        decision_lines = "\n".join(f"- {d}" for d in decisions) if decisions else "- Preserve dependency-safe execution order."
        action_lines = "\n".join(f"- {a}" for a in next_actions) if next_actions else "- Validate outputs and communicate completion."

        instructions = (
            f"# Skill: {skill_name}\n\n"
            f"Use this skill when the objective is similar to: \"{objective}\".\n\n"
            "## Procedure\n"
            "1. Validate dependency order before execution.\n"
            "2. Execute steps in topological order and checkpoint each completion.\n"
            "3. Produce a structured handoff with completed work, remaining work, and risks.\n\n"
            "## Proven Step Pattern\n"
            f"{step_lines}\n\n"
            "## Decisions Learned\n"
            f"{decision_lines}\n\n"
            "## Follow-up Actions\n"
            f"{action_lines}\n\n"
            "## Reference Handoff Snapshot\n"
            f"{self._clip(summary_text, 1500)}\n"
        )

        description = f"Workflow-promoted skill for objective: {objective}"
        tags = ["workflow", "promotion", _slugify(objective)]
        promoted = self.create_or_update(
            name=skill_name,
            description=description,
            instructions=instructions,
            tags=tags,
            source="workflow_promotion",
            workflow_id=workflow_id,
        )
        promoted["outcome_count"] = len(outcomes)
        return promoted
