from __future__ import annotations

import importlib.util
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_provider import JsonlMemoryProvider


def _tokenize(text: str) -> set[str]:
    return {x for x in re.findall(r"[a-z0-9]+", text.lower()) if x}


def _make_title(kind: str, content: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z0-9]+", content.strip()) if w]
    head = " ".join(words[:6]).strip() or "Memory Entry"
    prefix = (kind or "note").strip().title()
    return f"{prefix}: {head[:80]}"


@dataclass
class _MemoryRow:
    scope: str
    topic: str
    title: str
    content: str
    saved: str = ""
    meta_line: str = ""


class _JsonlBackend:
    def __init__(self, workspace_root: str) -> None:
        self.provider = JsonlMemoryProvider(workspace_root)

    @property
    def path(self) -> str:
        return str(self.provider.path)

    def add(
        self,
        *,
        content: str,
        kind: str,
        source: str,
        confidence: float,
        tags: list[str],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        entry = self.provider.add(
            content=content,
            kind=kind,
            source=source,
            confidence=confidence,
            tags=tags,
            metadata=metadata,
        )
        return {
            "id": entry.id,
            "timestamp": entry.timestamp,
            "content": entry.content,
            "kind": entry.kind,
            "source": entry.source,
            "confidence": entry.confidence,
            "tags": entry.tags,
            "metadata": entry.metadata,
            "path": str(self.provider.path),
        }

    def search(self, *, query: str, limit: int) -> list[dict[str, Any]]:
        return self.provider.search(query, limit=limit)

    def prefetch(self, *, query: str, limit: int) -> str:
        return self.provider.prefetch(query, limit=limit)


class _TauMemoryBackend:
    def __init__(self, workspace_root: str) -> None:
        module = self._load_tau_memory_module()
        self._memory_types = set(getattr(module, "MEMORY_TYPES", ("user", "feedback", "project", "reference")))
        self._store = module.MemoryStore(workspace_root)
        self._store.ensure_dir()

    @staticmethod
    def _load_tau_memory_module() -> Any:
        root = Path(__file__).resolve().parents[1]
        target = root / "tau-memory" / "extensions" / "memory" / "extension.py"
        if not target.exists():
            raise FileNotFoundError(f"tau-memory extension not found at {target}")
        mod_name = "_tau_memory_ext_for_assistant"
        spec = importlib.util.spec_from_file_location(mod_name, str(target))
        if spec is None or spec.loader is None:
            raise ImportError("Unable to load tau-memory extension module spec")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @property
    def path(self) -> str:
        return f"local={self._store.root}, global={self._store.global_root}"

    def _extract_rows(self) -> list[_MemoryRow]:
        rows: list[_MemoryRow] = []
        for topic in self._store.list_topics():
            name = str(topic.get("name", "")).strip()
            scope = str(topic.get("scope", "local")).strip() or "local"
            if not name or name.lower() == "memory":
                continue
            raw = self._store.read_topic(name=name, scope=scope)
            if not raw.strip():
                continue
            chunks = re.split(r"\n##\s+", raw)
            for idx, chunk in enumerate(chunks):
                text = chunk.strip()
                if not text:
                    continue
                if idx == 0 and text.startswith("#"):
                    continue
                lines = text.splitlines()
                title = lines[0].strip()
                meta_line = ""
                body_lines = lines[1:]
                if body_lines and body_lines[0].strip().startswith("*type:"):
                    meta_line = body_lines[0].strip()
                    body_lines = body_lines[1:]
                body = "\n".join(body_lines).strip()
                saved_match = re.search(r"saved:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", meta_line)
                saved = saved_match.group(1) if saved_match else ""
                rows.append(_MemoryRow(scope=scope, topic=name, title=title, content=body, saved=saved, meta_line=meta_line))
        return rows

    def add(
        self,
        *,
        content: str,
        kind: str,
        source: str,
        confidence: float,
        tags: list[str],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        memory_type = kind if kind in self._memory_types else "project"
        topic = kind if kind and kind not in self._memory_types else None
        merged_metadata = dict(metadata or {})
        if tags:
            merged_metadata.setdefault("tags", tags)
        if kind and kind not in self._memory_types:
            merged_metadata.setdefault("assistant_kind", kind)
        payload = content.strip()
        if merged_metadata:
            payload = f"{payload}\n\n```json\n{json.dumps(merged_metadata, ensure_ascii=False, indent=2)}\n```"
        title = _make_title(kind=kind or memory_type, content=content)
        written_path = self._store.save_memory(
            title=title,
            content=payload,
            memory_type=memory_type,
            topic=topic,
            confidence=confidence,
            source=source,
            explicitness="explicit",
        )
        return {
            "id": f"mem-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "title": title,
            "content": content.strip(),
            "kind": kind,
            "source": source,
            "confidence": max(0.0, min(1.0, float(confidence))),
            "tags": tags,
            "metadata": merged_metadata,
            "path": written_path,
            "backend": "tau-memory",
        }

    def search(self, *, query: str, limit: int) -> list[dict[str, Any]]:
        q = (query or "").strip()
        if not q:
            return []
        q_tokens = _tokenize(q)
        scored: list[tuple[float, _MemoryRow]] = []
        for row in self._extract_rows():
            hay = " ".join([row.title, row.content, row.topic, row.scope, row.meta_line]).lower()
            if q.lower() in hay:
                score = 2.0
            else:
                overlap = len(_tokenize(hay) & q_tokens)
                if overlap == 0:
                    continue
                score = float(overlap)
            if row.saved:
                score += 0.15
            scored.append((score, row))
        scored.sort(key=lambda x: (x[0], x[1].saved), reverse=True)
        return [
            {
                "scope": row.scope,
                "topic": row.topic,
                "title": row.title,
                "content": row.content[:1000],
                "saved": row.saved,
                "score": float(score),
            }
            for score, row in scored[: max(1, int(limit))]
        ]

    def prefetch(self, *, query: str, limit: int) -> str:
        rows = self.search(query=query, limit=limit)
        if not rows:
            return ""
        lines = ["Relevant memory context:"]
        for row in rows:
            lines.append(f"- [{row['topic']}/{row['scope']}] {row['title']}: {row['content']}")
        return "\n".join(lines)


class MemoryManager:
    """Thin orchestration layer for assistant memory operations."""

    def __init__(self, workspace_root: str) -> None:
        self.workspace_root = workspace_root
        self.backend: _TauMemoryBackend | _JsonlBackend = self._build_backend(workspace_root)

    def set_workspace_root(self, workspace_root: str) -> None:
        self.workspace_root = workspace_root
        self.backend = self._build_backend(workspace_root)

    def _build_backend(self, workspace_root: str) -> _TauMemoryBackend | _JsonlBackend:
        try:
            return _TauMemoryBackend(workspace_root)
        except Exception:
            return _JsonlBackend(workspace_root)

    def add_memory(
        self,
        *,
        content: str,
        kind: str = "fact",
        source: str = "",
        confidence: float = 0.8,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.backend.add(
            content=content,
            kind=kind,
            source=source,
            confidence=confidence,
            tags=tags or [],
            metadata=metadata or {},
        )

    def search_memories(self, *, query: str, limit: int = 5) -> list[dict[str, Any]]:
        return self.backend.search(query=query, limit=max(1, int(limit)))

    def prefetch_context(self, *, query: str, limit: int = 3) -> str:
        return self.backend.prefetch(query=query, limit=max(1, int(limit)))

    def on_workflow_complete(
        self,
        *,
        workflow_id: str,
        objective: str,
        outcomes: list[dict[str, str]],
    ) -> dict[str, Any]:
        completed = len([x for x in outcomes if x.get("status") == "completed"])
        total = len(outcomes)
        summary = f"Workflow '{objective}' completed {completed}/{total} steps (id={workflow_id})."
        return self.add_memory(
            content=summary,
            kind="workflow",
            source="assistant_workflow_run",
            confidence=0.9 if total > 0 and completed == total else 0.7,
            metadata={"workflow_id": workflow_id, "completed_steps": completed, "total_steps": total},
        )
