from __future__ import annotations

import re
from dataclasses import dataclass

from planner import PlanStep


@dataclass
class PolicyDecision:
    allow: bool
    requires_approval: bool
    risk: str
    reason: str = ""


class WorkflowPolicyEnforcer:
    """Assistant-local workflow policy gate for step execution."""

    def __init__(self, *, profile: str = "balanced", approved_risky_actions: bool = False) -> None:
        self.profile = (profile or "balanced").strip().lower()
        self.approved_risky_actions = bool(approved_risky_actions)

    @staticmethod
    def _is_destructive_shell(command: str) -> bool:
        risky = [
            r"\brm\s+-rf\b",
            r"\bmkfs\b",
            r"\bdd\b",
            r"\bshutdown\b",
            r"\breboot\b",
            r"\bhalt\b",
            r"\bcurl\b.*\|\s*sh\b",
            r"\bwget\b.*\|\s*sh\b",
        ]
        c = command.lower()
        return any(re.search(p, c) for p in risky)

    def classify(self, step: PlanStep) -> str:
        action = (step.action or "noop").strip().lower()
        if action in {"noop", "enqueue_prompt"}:
            return "low"
        if action == "memory_add":
            return "low"
        if action == "connector_action":
            ca = (step.connector_action or "").strip().lower()
            if ca in {"list_events", "get_note"}:
                return "low"
            if ca in {"save_note", "post_message", "send_email", "add_event"}:
                return "medium"
            return "medium"
        if action == "run_bash":
            command = str(step.payload.get("command", ""))
            return "high" if self._is_destructive_shell(command) else "medium"
        return "medium"

    def decide(self, step: PlanStep) -> PolicyDecision:
        risk = self.classify(step)
        if self.profile == "dev":
            return PolicyDecision(allow=True, requires_approval=False, risk=risk)
        if self.profile == "strict":
            if risk in {"high", "medium"}:
                return PolicyDecision(
                    allow=True,
                    requires_approval=True,
                    risk=risk,
                    reason=f"Approval required by strict policy for step {step.id} ({risk}).",
                )
            return PolicyDecision(allow=True, requires_approval=False, risk=risk)
        if risk in {"high", "medium"}:
            return PolicyDecision(
                allow=True,
                requires_approval=True,
                risk=risk,
                reason=f"Approval required by balanced policy for step {step.id} ({risk}).",
            )
        return PolicyDecision(allow=True, requires_approval=False, risk=risk)

    def enforce(self, step: PlanStep) -> None:
        decision = self.decide(step)
        if not decision.allow:
            raise PermissionError(decision.reason or f"Policy denied step {step.id}.")
        if decision.requires_approval and not self.approved_risky_actions:
            raise PermissionError(decision.reason or f"Approval required for step {step.id}.")
