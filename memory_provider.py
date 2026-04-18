from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _tokenize(text: str) -> set[str]:
    return {x for x in re.findall(r"[a-z0-9]+", text.lower()) if x}


@dataclass
class MemoryEntry:
    id: str
    timestamp: str
    content: str
    kind: str = "fact"
    source: str = ""
    confidence: float = 0.8
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class JsonlMemoryProvider:
    """Simple JSONL memory provider for tau-assistant."""

    def __init__(self, workspace_root: str) -> None:
        self.workspace_root = workspace_root

    @property
    def path(self) -> Path:
        return Path(self.workspace_root) / ".tau" / "assistant" / "memory.jsonl"

    def _ensure_parent(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def add(
        self,
        *,
        content: str,
        kind: str = "fact",
        source: str = "",
        confidence: float = 0.8,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryEntry:
        if not content.strip():
            raise ValueError("content must not be empty")
        self._ensure_parent()
        ts = datetime.now(timezone.utc).isoformat()
        entry = MemoryEntry(
            id=f"mem-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')}",
            timestamp=ts,
            content=content.strip(),
            kind=kind.strip() or "fact",
            source=source.strip(),
            confidence=max(0.0, min(1.0, float(confidence))),
            tags=[str(x).strip() for x in (tags or []) if str(x).strip()],
            metadata=metadata or {},
        )
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
        return entry

    def all(self) -> list[MemoryEntry]:
        target = self.path
        if not target.exists():
            return []
        rows: list[MemoryEntry] = []
        with target.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    rows.append(MemoryEntry(**obj))
                except Exception:
                    continue
        return rows

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        q = (query or "").strip()
        if not q:
            return []
        q_tokens = _tokenize(q)
        scored: list[tuple[float, MemoryEntry]] = []
        for row in self.all():
            hay = " ".join([row.content, " ".join(row.tags), row.kind, row.source]).lower()
            if q.lower() in hay:
                score = 2.0 + row.confidence
            else:
                overlap = len(_tokenize(hay) & q_tokens)
                if overlap == 0:
                    continue
                score = float(overlap) + row.confidence
            scored.append((score, row))

        scored.sort(key=lambda x: (x[0], x[1].timestamp), reverse=True)
        return [
            {
                "id": mem.id,
                "timestamp": mem.timestamp,
                "content": mem.content,
                "kind": mem.kind,
                "source": mem.source,
                "confidence": mem.confidence,
                "tags": mem.tags,
                "metadata": mem.metadata,
                "score": float(score),
            }
            for score, mem in scored[: max(1, int(limit))]
        ]

    def prefetch(self, query: str, *, limit: int = 3) -> str:
        rows = self.search(query, limit=limit)
        if not rows:
            return ""
        lines = ["Relevant memory context:"]
        for row in rows:
            lines.append(f"- [{row['kind']}] {row['content']}")
        return "\n".join(lines)
