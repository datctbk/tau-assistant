from __future__ import annotations

import os
import re
from pathlib import Path

from tau.core.policy import PolicyDecision
from tau.core.types import ToolCall


def _should_confirm_codegraph() -> bool:
    """Check if codegraph tools require user confirmation.

    If False: auto-allowed (low risk, no confirmation prompt).
    If True: requires confirmation (medium risk, asks allow? [y/N]).
    """
    raw = os.getenv("TAU_CONFIRM_CODEGRAPH")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    try:
        import tomllib
        cfg_file = Path.home() / ".tau" / "config.toml"
        if cfg_file.is_file():
            with open(cfg_file, "rb") as f:
                data = tomllib.load(f)
            for sec in ("policy", "tools", "codegraph", "defaults"):
                if sec in data and "confirm_codegraph" in data[sec]:
                    return bool(data[sec]["confirm_codegraph"])
    except Exception:
        pass

    return False


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
        if name.startswith("codegraph_"):
            return "medium" if _should_confirm_codegraph() else "low"
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
