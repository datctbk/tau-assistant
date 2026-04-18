from __future__ import annotations

import ast
import concurrent.futures
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tau.core.types import ErrorEvent, TextDelta


@dataclass
class DelegatePersona:
    name: str
    description: str
    system_prompt: str
    max_turns: int = 8
    allowed_tools: list[str] | None = None
    max_tool_result_chars: int = 0


def _parse_yaml_value(raw: str) -> Any:
    text = raw.strip()
    if not text:
        return ""
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed]
        except Exception:
            return []
    low = text.lower()
    if low in {"true", "false"}:
        return low == "true"
    try:
        return int(text)
    except Exception:
        return text


def _parse_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    text = raw.strip()
    if not text.startswith("---"):
        return {}, raw
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, raw
    fm_raw = parts[1].strip()
    body = parts[2].lstrip("\n")
    obj: dict[str, Any] = {}
    for line in fm_raw.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        obj[key.strip()] = _parse_yaml_value(value)
    return obj, body


def load_tau_agents_personas() -> dict[str, DelegatePersona]:
    personas: dict[str, DelegatePersona] = {}
    skills_dir = Path(__file__).resolve().parents[1] / "tau-agents" / "skills" / "built-in-agents"
    if not skills_dir.exists():
        return personas
    for md_file in sorted(skills_dir.glob("*.md")):
        raw = md_file.read_text(encoding="utf-8").strip()
        if not raw:
            continue
        fm, body = _parse_frontmatter(raw)
        prompt = body.strip()
        if not prompt:
            continue
        name = md_file.stem
        personas[name] = DelegatePersona(
            name=name,
            description=str(fm.get("description", name)).strip(),
            system_prompt=prompt,
            max_turns=int(fm.get("max_turns", 8)),
            allowed_tools=[str(x) for x in fm.get("allowed_tools", [])] if isinstance(fm.get("allowed_tools"), list) else None,
            max_tool_result_chars=int(fm.get("max_tool_result_chars", 0) or 0),
        )
    return personas


def _collect_subagent_text(events: list[Any]) -> str:
    text_parts: list[str] = []
    for event in events:
        if isinstance(event, TextDelta) and not getattr(event, "is_thinking", False):
            text_parts.append(event.text)
        elif isinstance(event, ErrorEvent):
            raise RuntimeError(f"Sub-agent error: {event.message}")
    result = "".join(text_parts).strip()
    return result or "(Sub-agent returned no text output.)"


class SubagentDelegator:
    def __init__(self, ext_context: Any, personas: dict[str, DelegatePersona] | None = None) -> None:
        self.ext_context = ext_context
        self.personas = personas or {}

    def _resolve_prompt(
        self,
        *,
        persona: str = "",
        system_prompt: str = "",
        max_turns: int = 8,
    ) -> tuple[str, int, list[str] | None, int]:
        if system_prompt.strip():
            return system_prompt.strip(), max(1, int(max_turns or 8)), None, 0
        key = persona.strip()
        if key:
            p = self.personas.get(key)
            if p is None:
                raise ValueError(f"Unknown persona '{key}'. Available: {', '.join(sorted(self.personas.keys())) or '(none)'}")
            return p.system_prompt, p.max_turns, p.allowed_tools, p.max_tool_result_chars
        return (
            "You are a helpful sub-agent. Complete the assigned task thoroughly and concisely.",
            max(1, int(max_turns or 8)),
            None,
            0,
        )

    def run_one(
        self,
        *,
        task: str,
        persona: str = "",
        system_prompt: str = "",
        max_turns: int = 8,
        model: str = "",
    ) -> str:
        if self.ext_context is None:
            raise RuntimeError("Extension context is not initialized.")
        prompt, turns, allowed_tools, max_tool_result_chars = self._resolve_prompt(
            persona=persona,
            system_prompt=system_prompt,
            max_turns=max_turns,
        )
        with self.ext_context.create_sub_session(
            model=(model.strip() or None),
            system_prompt=prompt,
            max_turns=turns,
            session_name=f"sub-agent:{persona or 'default'}",
            allowed_tools=allowed_tools,
            max_tool_result_chars=max_tool_result_chars,
        ) as sub:
            events = [event for event in sub.prompt(task)]
        return _collect_subagent_text(events)

    def run_parallel(
        self,
        *,
        tasks: list[dict[str, str]],
        persona: str = "",
        system_prompt: str = "",
        max_turns: int = 8,
        model: str = "",
        max_workers: int = 3,
    ) -> list[dict[str, Any]]:
        cap = max(1, int(max_workers or 3))

        def _worker(item: dict[str, str]) -> dict[str, Any]:
            tid = str(item.get("id", "")).strip() or f"task-{abs(hash(str(item.get('task', '')))) % 100000}"
            task = str(item.get("task", "")).strip()
            if not task:
                return {"id": tid, "status": "failed", "error": "task is required"}
            local_persona = str(item.get("persona", "")).strip() or persona
            try:
                out = self.run_one(
                    task=task,
                    persona=local_persona,
                    system_prompt=system_prompt,
                    max_turns=max_turns,
                    model=model,
                )
                return {"id": tid, "status": "completed", "persona": local_persona, "result": out}
            except Exception as exc:  # noqa: BLE001
                return {"id": tid, "status": "failed", "persona": local_persona, "error": str(exc)}

        results: list[dict[str, Any]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=cap) as ex:
            futs = [ex.submit(_worker, item) for item in tasks]
            for fut in concurrent.futures.as_completed(futs):
                results.append(fut.result())
        # Stable output order by task id for deterministic downstream checks.
        results.sort(key=lambda x: str(x.get("id", "")))
        return results
