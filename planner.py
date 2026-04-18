from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlanStep:
    id: str
    title: str
    depends_on: list[str] = field(default_factory=list)
    action: str = "noop"
    connector: str = ""
    connector_action: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    retries: int = 0
    on_failure: str = "stop"  # stop | continue


@dataclass
class WorkflowPlan:
    id: str
    objective: str
    steps: list[PlanStep] = field(default_factory=list)

    def validate_dependencies(self) -> None:
        ids = {s.id for s in self.steps}
        for s in self.steps:
            for dep in s.depends_on:
                if dep not in ids:
                    raise ValueError(f"Unknown dependency {dep!r} for step {s.id!r}")

    def topo_order(self) -> list[str]:
        self.validate_dependencies()
        deps = {s.id: set(s.depends_on) for s in self.steps}
        order: list[str] = []
        free = [sid for sid, d in deps.items() if not d]

        while free:
            cur = free.pop(0)
            order.append(cur)
            for sid, d in deps.items():
                if cur in d:
                    d.remove(cur)
                    if not d and sid not in order and sid not in free:
                        free.append(sid)

        if len(order) != len(self.steps):
            raise ValueError("Dependency cycle detected")
        return order
