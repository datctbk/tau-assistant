from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class UserProfile:
    name: str = ""
    goals: list[str] = field(default_factory=list)
    preferences: dict[str, str] = field(default_factory=dict)
    boundaries: list[str] = field(default_factory=list)

    @staticmethod
    def path(workspace_root: str) -> Path:
        return Path(workspace_root) / ".tau" / "assistant" / "profile.json"

    def save(self, workspace_root: str) -> Path:
        target = self.path(workspace_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        return target

    @classmethod
    def load(cls, workspace_root: str) -> "UserProfile":
        target = cls.path(workspace_root)
        if not target.exists():
            return cls()
        data = json.loads(target.read_text(encoding="utf-8"))
        return cls(**data)
