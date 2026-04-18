from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from planner import WorkflowPlan


class ContextEngine(ABC):
    """Base contract for workflow context preparation and handoff generation."""

    @abstractmethod
    def build_execution_brief(
        self,
        *,
        objective: str,
        plan: WorkflowPlan,
        memory_context: str = "",
        memory_snapshot: str = "",
    ) -> str:
        """Build compact context for step execution prompts."""

    @abstractmethod
    def build_workflow_handoff(
        self,
        *,
        objective: str,
        plan: WorkflowPlan,
        outcomes: list[dict[str, str]],
        memory_context: str = "",
        memory_snapshot: str = "",
    ) -> dict[str, Any]:
        """Build structured handoff artifact after workflow execution."""
