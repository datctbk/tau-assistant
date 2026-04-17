from __future__ import annotations

import re

from tau.core.policy import PolicyDecision
from tau.core.types import ToolCall


class DefaultPolicyProfileEvaluator:
    """Profile-specific risk matrix kept outside tau core.

    This module is loaded by tau core policy hook when present.
    """

    @staticmethod
    def _is_destructive_shell(command: str) -> bool:
        risky = [
            r"\brm\s+-rf\b",
            r"\bmkfs\b",
            r"\bdd\b",
            r"\bshutdown\b",
            r"\breboot\b",
            r"\bhalt\b",
            r"\bchmod\s+777\b",
            r"\bchown\s+-R\b",
            r"\bcurl\b.*\|\s*sh\b",
            r"\bwget\b.*\|\s*sh\b",
            r">\s*/dev/sd",
        ]
        c = command.lower()
        return any(re.search(p, c) for p in risky)

    def _classify_risk(self, call: ToolCall) -> str:
        name = call.name
        if name in {"read_file", "list_dir", "search_files", "grep", "find", "ls", "task_events"}:
            return "low"
        if name in {"write_file", "edit_file", "task_update", "task_stop", "task_create"}:
            return "medium"
        if name == "run_bash":
            command = str(call.arguments.get("command", ""))
            return "high" if self._is_destructive_shell(command) else "medium"
        if name in {"web_search", "web_fetch", "agent"}:
            return "high"
        return "medium"

    def decide(self, *, profile: str, call: ToolCall) -> PolicyDecision:
        risk = self._classify_risk(call)

        if profile == "dev":
            return PolicyDecision(allow=True, requires_approval=False, risk=risk)

        if profile == "strict":
            if risk in {"high", "medium"}:
                return PolicyDecision(
                    allow=True,
                    requires_approval=True,
                    risk=risk,
                    reason=f"Approval required by strict policy: {call.name} ({risk})",
                )
            return PolicyDecision(allow=True, requires_approval=False, risk=risk)

        # balanced profile
        if risk in {"high", "medium"}:
            return PolicyDecision(
                allow=True,
                requires_approval=True,
                risk=risk,
                reason=f"Approval required by balanced policy: {call.name} ({risk})",
            )
        return PolicyDecision(allow=True, requires_approval=False, risk=risk)
