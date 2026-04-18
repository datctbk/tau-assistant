from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _safe_slug(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", text.strip().lower()).strip("-")
    return slug or "checkpoint"


class CheckpointManager:
    """Manual checkpoint helper for assistant state snapshots."""

    def __init__(self, workspace_root: str) -> None:
        self.workspace_root = workspace_root

    @property
    def checkpoint_dir(self) -> Path:
        p = Path(self.workspace_root) / ".tau" / "checkpoints"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def create_named_checkpoint(
        self,
        *,
        name: str,
        summary: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        if not name.strip():
            raise ValueError("name is required")
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        fp = self.checkpoint_dir / f"{ts}_named_{_safe_slug(name)}.json"
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "name": name.strip(),
            "summary": summary.strip(),
            "metadata": metadata or {},
            "type": "named_checkpoint",
        }
        fp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(fp)
