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
    def _parse_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
        text = raw.strip()
        if not text.startswith("---"):
            return {}, raw
        parts = text.split("---", 2)
        if len(parts) < 3:
            return {}, raw
        fm_raw = parts[1].strip()
        body = parts[2].lstrip("\n")
        try:
            obj = json.loads(fm_raw)
            if isinstance(obj, dict):
                return obj, body
        except Exception:
            pass
        return {}, body

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

    def improve_from_workflow(
        self,
        *,
        skill_name: str,
        objective: str,
        workflow_id: str,
        handoff: dict[str, Any],
        outcomes: list[dict[str, str]],
        max_improvement_chars: int = 2500,
    ) -> dict[str, Any]:
        current = self.read(name=skill_name)
        metadata, body = self._parse_frontmatter(str(current.get("content", "")))
        existing_desc = str(metadata.get("description", "")).strip() or f"Workflow skill for objective: {objective}"
        existing_tags = [str(t).strip() for t in metadata.get("tags", []) if str(t).strip()]
        uniq_tags = sorted(set(existing_tags + ["workflow", "learning-loop", _slugify(objective)]))

        completed_steps = [str(x) for x in handoff.get("completed_steps", []) if str(x).strip()]
        next_actions = [str(x) for x in handoff.get("next_actions", []) if str(x).strip()]
        failed_steps = [str(x.get("step_id", "")).strip() for x in outcomes if str(x.get("status", "")).strip() == "failed"]
        failed_steps = [x for x in failed_steps if x]
        summary = str(handoff.get("summary_text", "")).strip()

        improvement_lines: list[str] = []
        if completed_steps:
            improvement_lines.append(f"- Reuse completed pattern: {', '.join(completed_steps[:4])}.")
        if next_actions:
            improvement_lines.append(f"- Prioritize follow-up: {', '.join(next_actions[:3])}.")
        if failed_steps:
            improvement_lines.append(f"- Add guardrails for failures at steps: {', '.join(failed_steps[:3])}.")
        if summary:
            improvement_lines.append(f"- Snapshot cue: {self._clip(summary.replace(chr(10), ' '), 220)}")
        if not improvement_lines:
            improvement_lines.append("- No significant deltas detected; keep existing procedure.")

        improvement_block = (
            f"\n### {datetime.now(timezone.utc).isoformat()} (workflow: {workflow_id})\n"
            + "\n".join(improvement_lines)
            + "\n"
        )

        marker = "## Continuous Improvements"
        if marker in body:
            prefix, suffix = body.split(marker, 1)
            improved_section = (suffix + improvement_block).strip()
            improved_section = self._clip(improved_section, max_improvement_chars)
            new_body = prefix.rstrip() + "\n\n" + marker + "\n" + improved_section + "\n"
        else:
            new_body = body.rstrip() + "\n\n" + marker + "\n" + improvement_block

        updated = self.create_or_update(
            name=skill_name,
            description=existing_desc,
            instructions=new_body,
            tags=uniq_tags,
            source="workflow_learning_loop",
            workflow_id=workflow_id,
        )
        updated["outcome_count"] = len(outcomes)
        updated["mode"] = "improved"
        return updated

    def auto_learn_from_workflow(
        self,
        *,
        objective: str,
        workflow_id: str,
        handoff: dict[str, Any],
        outcomes: list[dict[str, str]],
        skill_name: str = "",
        min_completed_steps: int = 2,
    ) -> dict[str, Any]:
        completed = [x for x in outcomes if str(x.get("status", "")).strip() == "completed"]
        if len(completed) < max(1, int(min_completed_steps)):
            return {
                "triggered": False,
                "reason": "not_enough_completed_steps",
                "completed_steps": len(completed),
                "required_min_completed_steps": max(1, int(min_completed_steps)),
            }

        resolved_name = skill_name.strip() or f"{objective.strip()} workflow"
        if self._skill_file(resolved_name).exists():
            updated = self.improve_from_workflow(
                skill_name=resolved_name,
                objective=objective,
                workflow_id=workflow_id,
                handoff=handoff,
                outcomes=outcomes,
            )
            return {"triggered": True, "mode": "improved", "skill": updated}

        created = self.promote_from_workflow(
            skill_name=resolved_name,
            objective=objective,
            workflow_id=workflow_id,
            handoff=handoff,
            outcomes=outcomes,
        )
        created["mode"] = "created"
        return {"triggered": True, "mode": "created", "skill": created}
