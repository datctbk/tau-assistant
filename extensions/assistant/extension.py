"""tau-assistant extension for tau.

Adds a personal-assistant layer as an extension (not tau core):
- Profile read/write tools
- Workflow plan validation and execution
- Cross-connector meeting-prep routine
- Slash commands for assistant status/profile
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tau.core.extension import Extension, ExtensionContext
from tau.core.types import ExtensionManifest, SlashCommand, ToolDefinition, ToolParameter


# Make sibling tau-assistant modules importable whether run from source or installed package.
_PKG_ROOT = Path(__file__).resolve().parents[2]
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from connector_router import ConnectorRouter
from connectors import CalendarConnector, ChatConnector, EmailConnector, NoteConnector
from checkpoint_manager import CheckpointManager
from context_compressor import WorkflowContextCompressor
from cross_connector_routines import run_meeting_prep_routine
from dialectic_profile import DialecticProfileManager
from insights_engine import AssistantInsightsEngine
from memory_manager import MemoryManager
from planner import PlanStep, WorkflowPlan
from profile import UserProfile
from routine_delivery import RoutineDeliveryRunner
from routine_engine import Routine, RoutineEngine
from session_recall import SessionRecallEngine
from skill_manager import SkillManager
from subagent_delegate import SubagentDelegator, load_tau_agents_personas
from web_source_ranker import normalize_and_rank_sources
from workflow_executor import WorkflowExecutor
from workflow_policy import WorkflowPolicyEnforcer
from workflow_runner import (
    WorkflowRunner,
    append_assistant_event,
    append_audit_record,
    make_assistant_event,
)


def _json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _parse_json_object(raw: str, *, field: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field} must be valid JSON object: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{field} must be a JSON object.")
    return parsed


def _parse_json_array(raw: str, *, field: str) -> list[Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field} must be valid JSON array: {exc}") from exc
    if not isinstance(parsed, list):
        raise ValueError(f"{field} must be a JSON array.")
    return parsed


class AssistantExtension(Extension):
    manifest = ExtensionManifest(
        name="assistant",
        version="0.1.0",
        description="Personal assistant extension with profile, planning, workflows, and routines.",
        author="datctbk",
    )

    def __init__(self) -> None:
        self._ext_context: ExtensionContext | None = None
        self._workspace_root = "."
        self._memory = MemoryManager(self._workspace_root)
        self._dialectic = DialecticProfileManager(self._workspace_root)
        self._skills = SkillManager(self._workspace_root)
        self._checkpoints = CheckpointManager(self._workspace_root)
        self._insights = AssistantInsightsEngine(self._workspace_root)
        self._context_engine = WorkflowContextCompressor()
        self._delegate_personas = load_tau_agents_personas()

    def on_load(self, context: ExtensionContext) -> None:
        self._ext_context = context
        agent_cfg = getattr(context, "_agent_config", None)
        if agent_cfg and getattr(agent_cfg, "workspace_root", None):
            self._workspace_root = str(agent_cfg.workspace_root)
        self._memory.set_workspace_root(self._workspace_root)
        self._dialectic = DialecticProfileManager(self._workspace_root)
        self._skills = SkillManager(self._workspace_root)
        self._checkpoints = CheckpointManager(self._workspace_root)
        self._insights = AssistantInsightsEngine(self._workspace_root)
        self._delegate_personas = load_tau_agents_personas()

    def tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="assistant_profile_get",
                description="Read the assistant user profile (goals, preferences, boundaries).",
                parameters={},
                handler=self._handle_profile_get,
            ),
            ToolDefinition(
                name="assistant_profile_set",
                description=(
                    "Create or update the assistant user profile. "
                    "Pass JSON strings for goals/preferences/boundaries."
                ),
                parameters={
                    "name": ToolParameter(
                        type="string",
                        description="Optional user name to set.",
                        required=False,
                    ),
                    "goals_json": ToolParameter(
                        type="string",
                        description='Optional JSON array, e.g. ["ship quickly","high quality"].',
                        required=False,
                    ),
                    "preferences_json": ToolParameter(
                        type="string",
                        description='Optional JSON object, e.g. {"tone":"concise","risk":"balanced"}.',
                        required=False,
                    ),
                    "boundaries_json": ToolParameter(
                        type="string",
                        description='Optional JSON array, e.g. ["never run rm -rf"].',
                        required=False,
                    ),
                },
                handler=self._handle_profile_set,
            ),
            ToolDefinition(
                name="assistant_dialectic_profile_get",
                description="Read advanced dialectic user model (tradeoff axes, confidence, evidence).",
                parameters={},
                handler=self._handle_dialectic_profile_get,
            ),
            ToolDefinition(
                name="assistant_dialectic_profile_update",
                description="Manually update a dialectic dimension with score/confidence and rationale.",
                parameters={
                    "dimension": ToolParameter(
                        type="string",
                        description="Dimension key (e.g. speed_vs_quality, autonomy_vs_control).",
                    ),
                    "score": ToolParameter(
                        type="number",
                        description="Score between -1 and +1.",
                    ),
                    "confidence": ToolParameter(
                        type="number",
                        description="Confidence between 0 and 1.",
                    ),
                    "rationale": ToolParameter(
                        type="string",
                        description="Optional rationale text.",
                        required=False,
                    ),
                    "evidence_json": ToolParameter(
                        type="string",
                        description='Optional JSON array of evidence snippets.',
                        required=False,
                    ),
                },
                handler=self._handle_dialectic_profile_update,
            ),
            ToolDefinition(
                name="assistant_dialectic_profile_infer",
                description="Infer dialectic profile from user profile, memory context, and optional evidence text.",
                parameters={
                    "query": ToolParameter(
                        type="string",
                        description="Optional memory query used to gather evidence context.",
                        required=False,
                    ),
                    "evidence_text": ToolParameter(
                        type="string",
                        description="Optional extra evidence text.",
                        required=False,
                    ),
                    "notes": ToolParameter(
                        type="string",
                        description="Optional note stored on dialectic profile.",
                        required=False,
                    ),
                },
                handler=self._handle_dialectic_profile_infer,
            ),
            ToolDefinition(
                name="assistant_plan_validate",
                description="Validate a workflow plan and return dependency-safe topological order.",
                parameters={
                    "objective": ToolParameter(
                        type="string",
                        description="Workflow objective.",
                    ),
                    "steps_json": ToolParameter(
                        type="string",
                        description=(
                            "JSON array of steps. "
                            'Each step: {"id":"s1","title":"...","depends_on":["s0"]}.'
                        ),
                    ),
                },
                handler=self._handle_plan_validate,
            ),
            ToolDefinition(
                name="assistant_workflow_run",
                description=(
                    "Run a dependency-ordered assistant workflow and checkpoint each completed step."
                ),
                parameters={
                    "objective": ToolParameter(
                        type="string",
                        description="Workflow objective.",
                    ),
                    "steps_json": ToolParameter(
                        type="string",
                        description=(
                            "JSON array of steps. "
                            'Each step: {"id":"s1","title":"...","depends_on":["s0"]}.'
                        ),
                    ),
                    "workflow_id": ToolParameter(
                        type="string",
                        description="Optional workflow id. Auto-generated if omitted.",
                        required=False,
                    ),
                    "execution_mode": ToolParameter(
                        type="string",
                        description="dry_run, enqueue_prompts, or execute.",
                        enum=["dry_run", "enqueue_prompts", "execute"],
                        required=False,
                    ),
                    "resume": ToolParameter(
                        type="boolean",
                        description="Resume from saved workflow state if available.",
                        required=False,
                    ),
                    "policy_profile": ToolParameter(
                        type="string",
                        description="Policy profile for real execution: dev, balanced, strict.",
                        enum=["dev", "balanced", "strict"],
                        required=False,
                    ),
                    "approved_risky_actions": ToolParameter(
                        type="boolean",
                        description="Explicit approval gate for medium/high risk actions under balanced/strict policy.",
                        required=False,
                    ),
                    "promote_to_skill": ToolParameter(
                        type="boolean",
                        description="When true, promote workflow handoff into a reusable assistant skill.",
                        required=False,
                    ),
                    "skill_name": ToolParameter(
                        type="string",
                        description="Optional skill name for promotion. Defaults to objective-derived name.",
                        required=False,
                    ),
                    "auto_learn_skill": ToolParameter(
                        type="boolean",
                        description="Enable automatic skill creation/improvement loop from workflow outcomes.",
                        required=False,
                    ),
                    "auto_learn_min_completed_steps": ToolParameter(
                        type="integer",
                        description="Minimum completed steps required before auto-learning triggers (default 2).",
                        required=False,
                    ),
                },
                handler=self._handle_workflow_run,
            ),
            ToolDefinition(
                name="assistant_meeting_prep",
                description=(
                    "Run cross-connector meeting prep (calendar -> notes + chat, optional email digest)."
                ),
                parameters={
                    "events_json": ToolParameter(
                        type="string",
                        description="Optional JSON array of calendar events.",
                        required=False,
                    ),
                    "chat_channel": ToolParameter(
                        type="string",
                        description="Target chat channel.",
                        required=False,
                    ),
                    "send_email_digest": ToolParameter(
                        type="boolean",
                        description="Whether to send email digest.",
                        required=False,
                    ),
                    "digest_to": ToolParameter(
                        type="string",
                        description="Recipient when send_email_digest=true.",
                        required=False,
                    ),
                },
                handler=self._handle_meeting_prep,
            ),
            ToolDefinition(
                name="assistant_subagent_run",
                description="Delegate a focused task to a sub-agent session (optionally using tau-agents persona).",
                parameters={
                    "task": ToolParameter(
                        type="string",
                        description="Task text delegated to sub-agent.",
                    ),
                    "persona": ToolParameter(
                        type="string",
                        description="Optional persona from tau-agents built-ins (explore, plan, verify).",
                        required=False,
                    ),
                    "system_prompt": ToolParameter(
                        type="string",
                        description="Optional direct system prompt override.",
                        required=False,
                    ),
                    "max_turns": ToolParameter(
                        type="integer",
                        description="Optional max turns for sub-agent (default 8).",
                        required=False,
                    ),
                    "model": ToolParameter(
                        type="string",
                        description="Optional model override for sub-agent.",
                        required=False,
                    ),
                },
                handler=self._handle_subagent_run,
            ),
            ToolDefinition(
                name="assistant_subagent_parallel",
                description="Run multiple delegated tasks in parallel sub-agent sessions.",
                parameters={
                    "tasks_json": ToolParameter(
                        type="string",
                        description='JSON array like [{"id":"t1","task":"...","persona":"explore"}].',
                    ),
                    "persona": ToolParameter(
                        type="string",
                        description="Optional default persona for tasks without persona.",
                        required=False,
                    ),
                    "system_prompt": ToolParameter(
                        type="string",
                        description="Optional shared system prompt override.",
                        required=False,
                    ),
                    "max_turns": ToolParameter(
                        type="integer",
                        description="Optional max turns per task (default 8).",
                        required=False,
                    ),
                    "model": ToolParameter(
                        type="string",
                        description="Optional model override for all sub-agents.",
                        required=False,
                    ),
                    "max_workers": ToolParameter(
                        type="integer",
                        description="Optional max parallel workers (default 3).",
                        required=False,
                    ),
                },
                handler=self._handle_subagent_parallel,
            ),
            ToolDefinition(
                name="assistant_routine_manage",
                description="Create, list, update, delete, enable, or disable assistant routines with delivery settings.",
                parameters={
                    "action": ToolParameter(
                        type="string",
                        description="One of: create, list, delete, enable, disable.",
                        enum=["create", "list", "delete", "enable", "disable"],
                    ),
                    "routine_id": ToolParameter(
                        type="string",
                        description="Routine id for create/delete/enable/disable.",
                        required=False,
                    ),
                    "title": ToolParameter(
                        type="string",
                        description="Routine title for create.",
                        required=False,
                    ),
                    "interval_minutes": ToolParameter(
                        type="integer",
                        description="Routine interval in minutes for create (default 60).",
                        required=False,
                    ),
                    "delivery_connector": ToolParameter(
                        type="string",
                        description="Delivery connector: chat, email, or note (default chat).",
                        enum=["chat", "email", "note"],
                        required=False,
                    ),
                    "delivery_target": ToolParameter(
                        type="string",
                        description="Connector-specific target (chat channel, email address, or note id).",
                        required=False,
                    ),
                    "delivery_template": ToolParameter(
                        type="string",
                        description="Optional delivery template with variables: {routine_id}, {routine_title}, {timestamp}.",
                        required=False,
                    ),
                },
                handler=self._handle_routine_manage,
            ),
            ToolDefinition(
                name="assistant_routine_run_due",
                description="Run due routines and deliver outputs through configured connectors.",
                parameters={
                    "limit": ToolParameter(
                        type="integer",
                        description="Optional max due routines to run in one invocation (default 20).",
                        required=False,
                    ),
                },
                handler=self._handle_routine_run_due,
            ),
            ToolDefinition(
                name="assistant_session_search",
                description="Search saved tau sessions by semantic keyword overlap and return ranked candidates.",
                parameters={
                    "query": ToolParameter(
                        type="string",
                        description="Query text to match against session message history.",
                    ),
                    "limit": ToolParameter(
                        type="integer",
                        description="Optional number of sessions to return (default 5).",
                        required=False,
                    ),
                },
                handler=self._handle_session_search,
            ),
            ToolDefinition(
                name="assistant_session_recall",
                description="Recall and summarize a specific session (ID or prefix), optionally focused by query.",
                parameters={
                    "session_id": ToolParameter(
                        type="string",
                        description="Session id or unique prefix from .tau/sessions.",
                    ),
                    "query": ToolParameter(
                        type="string",
                        description="Optional focus query for targeted recall.",
                        required=False,
                    ),
                    "max_points": ToolParameter(
                        type="integer",
                        description="Optional max bullets in summary (default 6).",
                        required=False,
                    ),
                },
                handler=self._handle_session_recall,
            ),
            ToolDefinition(
                name="assistant_web_rank",
                description=(
                    "Normalize web result URLs, add source trust fields, and rank by trust + query relevance."
                ),
                parameters={
                    "query": ToolParameter(
                        type="string",
                        description="Original search query text for relevance scoring.",
                    ),
                    "results_json": ToolParameter(
                        type="string",
                        description=(
                            "JSON array of web results, each item like "
                            '{"title":"...","url":"...","snippet":"..."}'
                        ),
                    ),
                    "max_results": ToolParameter(
                        type="integer",
                        description="Optional maximum returned rows (default 10).",
                        required=False,
                    ),
                },
                handler=self._handle_web_rank,
            ),
            ToolDefinition(
                name="assistant_workflow_status",
                description="Read persisted workflow execution state and failure summary.",
                parameters={
                    "workflow_id": ToolParameter(
                        type="string",
                        description="Workflow id to inspect.",
                    ),
                },
                handler=self._handle_workflow_status,
            ),
            ToolDefinition(
                name="assistant_workflow_list",
                description="List saved workflow states ordered by most recently updated.",
                parameters={
                    "limit": ToolParameter(
                        type="integer",
                        description="Optional maximum number of states to return (default 20).",
                        required=False,
                    ),
                },
                handler=self._handle_workflow_list,
            ),
            ToolDefinition(
                name="assistant_memory_add",
                description="Add a memory entry to the assistant's persistent memory store.",
                parameters={
                    "content": ToolParameter(
                        type="string",
                        description="Memory content to store.",
                    ),
                    "kind": ToolParameter(
                        type="string",
                        description="Optional memory type, e.g. fact, preference, workflow.",
                        required=False,
                    ),
                    "source": ToolParameter(
                        type="string",
                        description="Optional source label for traceability.",
                        required=False,
                    ),
                    "confidence": ToolParameter(
                        type="number",
                        description="Optional confidence score between 0 and 1.",
                        required=False,
                    ),
                    "tags_json": ToolParameter(
                        type="string",
                        description='Optional JSON array of tags, e.g. ["release","deploy"].',
                        required=False,
                    ),
                    "metadata_json": ToolParameter(
                        type="string",
                        description='Optional JSON object with extra metadata.',
                        required=False,
                    ),
                },
                handler=self._handle_memory_add,
            ),
            ToolDefinition(
                name="assistant_memory_search",
                description="Search assistant memory entries by semantic keyword overlap.",
                parameters={
                    "query": ToolParameter(
                        type="string",
                        description="Search query text.",
                    ),
                    "limit": ToolParameter(
                        type="integer",
                        description="Optional number of results (default 5).",
                        required=False,
                    ),
                },
                handler=self._handle_memory_search,
            ),
            ToolDefinition(
                name="assistant_skill_manage",
                description="Create, read, list, delete, or promote assistant skills.",
                parameters={
                    "action": ToolParameter(
                        type="string",
                        description="One of: create, read, list, delete, promote.",
                        enum=["create", "read", "list", "delete", "promote"],
                    ),
                    "name": ToolParameter(
                        type="string",
                        description="Skill name (required for all actions except list).",
                        required=False,
                    ),
                    "description": ToolParameter(
                        type="string",
                        description="Description for create action.",
                        required=False,
                    ),
                    "instructions": ToolParameter(
                        type="string",
                        description="Instructions body for create action.",
                        required=False,
                    ),
                    "tags_json": ToolParameter(
                        type="string",
                        description='Optional JSON array of tags, e.g. ["release","workflow"].',
                        required=False,
                    ),
                    "objective": ToolParameter(
                        type="string",
                        description="Objective text for promote action.",
                        required=False,
                    ),
                    "workflow_id": ToolParameter(
                        type="string",
                        description="Workflow id for promote action.",
                        required=False,
                    ),
                    "handoff_json": ToolParameter(
                        type="string",
                        description="Workflow handoff as JSON object for promote action.",
                        required=False,
                    ),
                    "outcomes_json": ToolParameter(
                        type="string",
                        description="Workflow outcomes as JSON array for promote action.",
                        required=False,
                    ),
                },
                handler=self._handle_skill_manage,
            ),
            ToolDefinition(
                name="assistant_checkpoint_create",
                description="Create a named checkpoint with summary and optional metadata.",
                parameters={
                    "name": ToolParameter(
                        type="string",
                        description="Checkpoint name.",
                    ),
                    "summary": ToolParameter(
                        type="string",
                        description="Optional summary text for quick resume context.",
                        required=False,
                    ),
                    "metadata_json": ToolParameter(
                        type="string",
                        description="Optional JSON object for extra checkpoint metadata.",
                        required=False,
                    ),
                },
                handler=self._handle_checkpoint_create,
            ),
            ToolDefinition(
                name="assistant_insights",
                description="Generate assistant insights across checkpoints, skills, memory, routines, and audit logs.",
                parameters={},
                handler=self._handle_insights,
            ),
        ]

    def slash_commands(self) -> list[SlashCommand]:
        return [
            SlashCommand(
                name="assistant",
                description="Show assistant extension status and available tools.",
                usage="/assistant",
            ),
            SlashCommand(
                name="assistant-profile",
                description="Show the assistant profile.",
                usage="/assistant-profile",
            ),
        ]

    def handle_slash(self, command: str, args: str, context: ExtensionContext) -> bool:
        del args
        if command == "assistant":
            context.print(self._status_text())
            return True
        if command == "assistant-profile":
            context.print(self._handle_profile_get())
            return True
        return False

    def _status_text(self) -> str:
        return (
            "[bold cyan]tau-assistant[/bold cyan]\n"
            f"[dim]workspace: {self._workspace_root}[/dim]\n\n"
            "Tools:\n"
            "- assistant_profile_get\n"
            "- assistant_profile_set\n"
            "- assistant_dialectic_profile_get\n"
            "- assistant_dialectic_profile_update\n"
            "- assistant_dialectic_profile_infer\n"
            "- assistant_plan_validate\n"
            "- assistant_workflow_run\n"
            "- assistant_meeting_prep\n"
            "- assistant_subagent_run\n"
            "- assistant_subagent_parallel\n"
            "- assistant_routine_manage\n"
            "- assistant_routine_run_due\n"
            "- assistant_session_search\n"
            "- assistant_session_recall\n"
            "- assistant_web_rank\n"
            "- assistant_workflow_status\n"
            "- assistant_workflow_list\n"
            "- assistant_memory_add\n"
            "- assistant_memory_search\n"
            "- assistant_skill_manage\n"
            "- assistant_checkpoint_create\n"
            "- assistant_insights\n"
        )

    def _build_plan(self, objective: str, steps_json: str, workflow_id: str | None = None) -> WorkflowPlan:
        rows = _parse_json_array(steps_json, field="steps_json")
        steps: list[PlanStep] = []
        for idx, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError(f"steps_json[{idx}] must be an object.")
            step_id = str(row.get("id", "")).strip()
            title = str(row.get("title", "")).strip()
            depends_on = row.get("depends_on", [])
            action = str(row.get("action", "noop")).strip() or "noop"
            connector = str(row.get("connector", "")).strip()
            connector_action = str(row.get("connector_action", "")).strip()
            payload = row.get("payload", {})
            retries = row.get("retries", 0)
            on_failure = str(row.get("on_failure", "stop")).strip().lower() or "stop"
            if not step_id:
                raise ValueError(f"steps_json[{idx}].id is required.")
            if not title:
                raise ValueError(f"steps_json[{idx}].title is required.")
            if not isinstance(depends_on, list):
                raise ValueError(f"steps_json[{idx}].depends_on must be a list.")
            if not isinstance(payload, dict):
                raise ValueError(f"steps_json[{idx}].payload must be an object.")
            if on_failure not in {"stop", "continue"}:
                raise ValueError(f"steps_json[{idx}].on_failure must be 'stop' or 'continue'.")
            try:
                retries_val = max(0, int(retries))
            except Exception as exc:
                raise ValueError(f"steps_json[{idx}].retries must be an integer >= 0.") from exc
            steps.append(
                PlanStep(
                    id=step_id,
                    title=title,
                    depends_on=[str(x) for x in depends_on],
                    action=action,
                    connector=connector,
                    connector_action=connector_action,
                    payload={str(k): v for k, v in payload.items()},
                    retries=retries_val,
                    on_failure=on_failure,
                )
            )
        wf_id = workflow_id or f"wf-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        return WorkflowPlan(id=wf_id, objective=objective, steps=steps)

    def _handle_profile_get(self) -> str:
        profile = UserProfile.load(self._workspace_root)
        return _json_dumps(
            {
                "name": profile.name,
                "goals": profile.goals,
                "preferences": profile.preferences,
                "boundaries": profile.boundaries,
                "path": str(UserProfile.path(self._workspace_root)),
            }
        )

    def _handle_profile_set(
        self,
        name: str | None = None,
        goals_json: str | None = None,
        preferences_json: str | None = None,
        boundaries_json: str | None = None,
    ) -> str:
        profile = UserProfile.load(self._workspace_root)

        if name is not None:
            profile.name = name
        if goals_json is not None:
            goals = _parse_json_array(goals_json, field="goals_json")
            profile.goals = [str(x) for x in goals]
        if preferences_json is not None:
            prefs = _parse_json_object(preferences_json, field="preferences_json")
            profile.preferences = {str(k): str(v) for k, v in prefs.items()}
        if boundaries_json is not None:
            boundaries = _parse_json_array(boundaries_json, field="boundaries_json")
            profile.boundaries = [str(x) for x in boundaries]

        path = profile.save(self._workspace_root)
        return _json_dumps({"ok": True, "path": str(path), "profile": json.loads(self._handle_profile_get())})

    def _handle_plan_validate(self, objective: str, steps_json: str) -> str:
        plan = self._build_plan(objective=objective, steps_json=steps_json)
        order = plan.topo_order()
        return _json_dumps(
            {
                "ok": True,
                "workflow_id": plan.id,
                "objective": plan.objective,
                "step_count": len(plan.steps),
                "topo_order": order,
            }
        )

    def _handle_dialectic_profile_get(self) -> str:
        profile = self._dialectic.load()
        return _json_dumps({"ok": True, "dialectic_profile": self._dialectic.as_dict(profile)})

    def _handle_dialectic_profile_update(
        self,
        dimension: str,
        score: float,
        confidence: float,
        rationale: str = "",
        evidence_json: str | None = None,
    ) -> str:
        evidence: list[str] = []
        if evidence_json:
            evidence = [str(x) for x in _parse_json_array(evidence_json, field="evidence_json")]
        updated = self._dialectic.update_dimension(
            key=(dimension or "").strip(),
            score=float(score),
            confidence=float(confidence),
            rationale=rationale,
            evidence=evidence,
        )
        self._memory.add_memory(
            content=(
                f"Updated dialectic dimension {updated['key']} "
                f"score={updated['dimension']['score']:.2f} "
                f"confidence={updated['dimension']['confidence']:.2f}."
            ),
            kind="preference",
            source="assistant_dialectic_profile_update",
            confidence=0.84,
            tags=["dialectic", "profile"],
            metadata={"dimension": updated["key"]},
        )
        return _json_dumps({"ok": True, "updated": updated})

    def _handle_dialectic_profile_infer(
        self,
        query: str = "",
        evidence_text: str = "",
        notes: str = "",
    ) -> str:
        profile = UserProfile.load(self._workspace_root)
        query_text = (query or "preference priorities style risk quality speed").strip()
        memory_context = self._memory.prefetch_context(query=query_text, limit=6)
        combined = "\n".join(
            [
                f"name: {profile.name}",
                f"goals: {'; '.join(profile.goals)}",
                f"preferences: {json.dumps(profile.preferences, ensure_ascii=False)}",
                f"boundaries: {'; '.join(profile.boundaries)}",
                memory_context,
                (evidence_text or "").strip(),
            ]
        ).strip()
        inferred = self._dialectic.infer(evidence_text=combined, notes=notes)
        if inferred.get("updated"):
            self._memory.add_memory(
                content="Refreshed dialectic profile from profile+memory evidence context.",
                kind="preference",
                source="assistant_dialectic_profile_infer",
                confidence=0.8,
                tags=["dialectic", "inference"],
                metadata={"query": query_text},
            )
        return _json_dumps({"ok": True, "inference": inferred})

    def _handle_workflow_run(
        self,
        objective: str,
        steps_json: str,
        workflow_id: str | None = None,
        execution_mode: str = "dry_run",
        resume: bool = False,
        policy_profile: str = "balanced",
        approved_risky_actions: bool = False,
        promote_to_skill: bool = False,
        skill_name: str = "",
        auto_learn_skill: bool = False,
        auto_learn_min_completed_steps: int = 2,
    ) -> str:
        mode = (execution_mode or "dry_run").strip()
        if mode not in {"dry_run", "enqueue_prompts", "execute"}:
            return "Error: execution_mode must be one of: dry_run, enqueue_prompts, execute."
        policy = (policy_profile or "balanced").strip().lower()
        if policy not in {"dev", "balanced", "strict"}:
            return "Error: policy_profile must be one of: dev, balanced, strict."

        plan = self._build_plan(objective=objective, steps_json=steps_json, workflow_id=workflow_id)
        runner = WorkflowRunner(self._workspace_root)
        memory_context = self._memory.prefetch_context(query=objective, limit=3)
        memory_snapshot = self._context_engine.memory_snapshot(self._workspace_root)
        execution_brief = self._context_engine.build_execution_brief(
            objective=objective,
            plan=plan,
            memory_context=memory_context,
            memory_snapshot=memory_snapshot,
        )

        calendar = CalendarConnector()
        notes = NoteConnector()
        chat = ChatConnector()
        email = EmailConnector()
        router = ConnectorRouter()
        router.register(calendar)
        router.register(notes)
        router.register(chat)
        router.register(email)

        executor = WorkflowExecutor(
            workspace_root=self._workspace_root,
            memory=self._memory,
            router=router,
            ext_context=self._ext_context,
        )
        enforcer = WorkflowPolicyEnforcer(
            profile=policy,
            approved_risky_actions=approved_risky_actions,
        )

        def _execute_step(step: PlanStep) -> str:
            if mode == "execute":
                enforcer.enforce(step)
            return executor.execute_step(step, mode=mode, execution_brief=execution_brief)

        run_result = runner.run_with_recovery(plan, execute_step=_execute_step, resume=bool(resume))
        outcomes = [x for x in run_result.get("outcomes", []) if isinstance(x, dict)]
        handoff = self._context_engine.build_workflow_handoff(
            objective=objective,
            plan=plan,
            outcomes=outcomes,
            memory_context=memory_context,
            memory_snapshot=memory_snapshot,
        )
        handoff_checkpoint = runner.write_handoff_checkpoint(plan.id, handoff["summary_text"])
        handoff_memory = self._memory.add_memory(
            content=handoff["summary_text"],
            kind="project",
            source="assistant_workflow_handoff",
            confidence=0.85,
            tags=["workflow", "handoff"],
            metadata={
                "workflow_id": plan.id,
                "type": "handoff_summary",
                "remaining_steps": handoff["remaining_steps"],
            },
        )
        promotion: dict[str, Any] | None = None
        auto_learning: dict[str, Any] | None = None
        if bool(promote_to_skill):
            resolved_skill_name = skill_name.strip() or f"{objective.strip()} workflow"
            promotion = self._skills.promote_from_workflow(
                skill_name=resolved_skill_name,
                objective=objective,
                workflow_id=plan.id,
                handoff=handoff,
                outcomes=outcomes,
            )
            self._memory.add_memory(
                content=(
                    f"Promoted workflow '{plan.objective}' to skill '{resolved_skill_name}' "
                    f"from workflow_id={plan.id}."
                ),
                kind="reference",
                source="assistant_skill_manage",
                confidence=0.88,
                tags=["skill", "promotion"],
                metadata={
                    "workflow_id": plan.id,
                    "skill_name": resolved_skill_name,
                    "skill_path": promotion.get("path", ""),
                },
            )
        if bool(auto_learn_skill):
            resolved_skill_name = skill_name.strip() or f"{objective.strip()} workflow"
            auto_learning = self._skills.auto_learn_from_workflow(
                objective=objective,
                workflow_id=plan.id,
                handoff=handoff,
                outcomes=outcomes,
                skill_name=resolved_skill_name,
                min_completed_steps=max(1, int(auto_learn_min_completed_steps or 2)),
            )
            if auto_learning.get("triggered"):
                learned = auto_learning.get("skill", {})
                self._memory.add_memory(
                    content=(
                        f"Auto-learn loop {auto_learning.get('mode', 'updated')} skill "
                        f"'{resolved_skill_name}' from workflow_id={plan.id}."
                    ),
                    kind="reference",
                    source="assistant_skill_autolearn",
                    confidence=0.86,
                    tags=["skill", "learning-loop"],
                    metadata={
                        "workflow_id": plan.id,
                        "skill_name": resolved_skill_name,
                        "skill_path": str(learned.get("path", "")),
                        "mode": str(auto_learning.get("mode", "")),
                    },
                )
        memory_write = self._memory.on_workflow_complete(
            workflow_id=plan.id,
            objective=plan.objective,
            outcomes=outcomes,
        )
        return _json_dumps(
            {
                "ok": True,
                "workflow_id": plan.id,
                "objective": plan.objective,
                "execution_mode": mode,
                "run_status": run_result.get("status", "unknown"),
                "resume": bool(resume),
                "state_path": run_result.get("state_path", ""),
                "memory_context": memory_context,
                "memory_snapshot": memory_snapshot,
                "execution_brief": execution_brief,
                "memory_write": memory_write,
                "handoff_memory_write": handoff_memory,
                "handoff": handoff,
                "handoff_checkpoint": str(handoff_checkpoint),
                "skill_promotion": promotion,
                "skill_auto_learning": auto_learning,
                "outcomes": outcomes,
            }
        )

    def _build_connector_router(self) -> ConnectorRouter:
        router = ConnectorRouter()
        router.register(CalendarConnector())
        router.register(NoteConnector())
        router.register(ChatConnector())
        router.register(EmailConnector())
        return router

    def _handle_routine_manage(
        self,
        action: str,
        routine_id: str | None = None,
        title: str | None = None,
        interval_minutes: int = 60,
        delivery_connector: str = "chat",
        delivery_target: str = "",
        delivery_template: str = "",
    ) -> str:
        act = (action or "").strip().lower()
        engine = RoutineEngine.load_workspace(self._workspace_root)

        if act == "list":
            return _json_dumps(
                {
                    "ok": True,
                    "action": "list",
                    "count": len(engine.routines),
                    "routines": [r.__dict__ for r in engine.routines],
                }
            )

        rid = (routine_id or "").strip()
        if not rid:
            return "Error: routine_id is required for create/delete/enable/disable."

        if act == "create":
            routine_title = (title or "").strip()
            if not routine_title:
                return "Error: title is required for action=create."
            routine = Routine(
                id=rid,
                title=routine_title,
                interval_minutes=max(1, int(interval_minutes or 60)),
                enabled=True,
                delivery_connector=(delivery_connector or "chat").strip().lower() or "chat",
                delivery_target=(delivery_target or "").strip(),
                delivery_template=(delivery_template or "").strip(),
            )
            engine.upsert(routine)
            path = engine.save_workspace(self._workspace_root)
            return _json_dumps({"ok": True, "action": "create", "routine": routine.__dict__, "path": path})

        if act == "delete":
            removed = engine.delete(rid)
            path = engine.save_workspace(self._workspace_root)
            return _json_dumps({"ok": True, "action": "delete", "removed": removed, "path": path})

        if act in {"enable", "disable"}:
            found = False
            for r in engine.routines:
                if r.id == rid:
                    r.enabled = act == "enable"
                    found = True
                    break
            if not found:
                return f"Error: routine not found: {rid}"
            path = engine.save_workspace(self._workspace_root)
            return _json_dumps({"ok": True, "action": act, "routine_id": rid, "path": path})

        return "Error: action must be one of create, list, delete, enable, disable."

    def _handle_routine_run_due(self, limit: int = 20) -> str:
        engine = RoutineEngine.load_workspace(self._workspace_root)
        due = engine.due_routines()
        cap = max(1, int(limit or 20))
        selected = due[:cap]
        runner = RoutineDeliveryRunner(self._build_connector_router())

        deliveries: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        for routine in selected:
            try:
                rec = runner.deliver(routine)
                engine.mark_run(routine.id)
                deliveries.append(rec)
                append_audit_record(
                    self._workspace_root,
                    "routine.delivery_sent",
                    {
                        "routine_id": routine.id,
                        "connector": rec.get("connector", ""),
                        "action": rec.get("action", ""),
                    },
                )
                append_assistant_event(
                    self._workspace_root,
                    make_assistant_event(
                        family="routine",
                        name="delivery_sent",
                        payload={
                            "routine_id": routine.id,
                            "connector": rec.get("connector", ""),
                        },
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                failures.append({"routine_id": routine.id, "error": str(exc)})
                append_audit_record(
                    self._workspace_root,
                    "routine.delivery_failed",
                    {"routine_id": routine.id, "error": str(exc)},
                )
                append_assistant_event(
                    self._workspace_root,
                    make_assistant_event(
                        family="routine",
                        name="delivery_failed",
                        payload={"routine_id": routine.id, "error": str(exc)},
                        severity="warning",
                    ),
                )

        path = engine.save_workspace(self._workspace_root)
        return _json_dumps(
            {
                "ok": True,
                "due_count": len(due),
                "run_count": len(selected),
                "delivered_count": len(deliveries),
                "failed_count": len(failures),
                "deliveries": deliveries,
                "failures": failures,
                "path": path,
            }
        )

    def _handle_subagent_run(
        self,
        task: str,
        persona: str = "",
        system_prompt: str = "",
        max_turns: int = 8,
        model: str = "",
    ) -> str:
        delegator = SubagentDelegator(self._ext_context, personas=self._delegate_personas)
        result = delegator.run_one(
            task=task,
            persona=persona,
            system_prompt=system_prompt,
            max_turns=max_turns,
            model=model,
        )
        return _json_dumps(
            {
                "ok": True,
                "persona": persona,
                "result": result,
            }
        )

    def _handle_subagent_parallel(
        self,
        tasks_json: str,
        persona: str = "",
        system_prompt: str = "",
        max_turns: int = 8,
        model: str = "",
        max_workers: int = 3,
    ) -> str:
        tasks = _parse_json_array(tasks_json, field="tasks_json")
        rows = [x for x in tasks if isinstance(x, dict)]
        delegator = SubagentDelegator(self._ext_context, personas=self._delegate_personas)
        results = delegator.run_parallel(
            tasks=[{str(k): str(v) for k, v in row.items()} for row in rows],
            persona=persona,
            system_prompt=system_prompt,
            max_turns=max_turns,
            model=model,
            max_workers=max_workers,
        )
        completed = len([x for x in results if x.get("status") == "completed"])
        failed = len([x for x in results if x.get("status") == "failed"])
        return _json_dumps(
            {
                "ok": True,
                "count": len(results),
                "completed": completed,
                "failed": failed,
                "results": results,
            }
        )

    def _handle_memory_add(
        self,
        content: str,
        kind: str = "fact",
        source: str = "",
        confidence: float = 0.8,
        tags_json: str | None = None,
        metadata_json: str | None = None,
    ) -> str:
        tags: list[str] = []
        metadata: dict[str, Any] = {}
        if tags_json is not None:
            parsed_tags = _parse_json_array(tags_json, field="tags_json")
            tags = [str(x) for x in parsed_tags]
        if metadata_json is not None:
            metadata = _parse_json_object(metadata_json, field="metadata_json")
        written = self._memory.add_memory(
            content=content,
            kind=kind,
            source=source,
            confidence=confidence,
            tags=tags,
            metadata=metadata,
        )
        return _json_dumps({"ok": True, "memory": written})

    def _handle_workflow_status(self, workflow_id: str) -> str:
        runner = WorkflowRunner(self._workspace_root)
        wid = (workflow_id or "").strip()
        if not wid:
            return "Error: workflow_id is required."
        state = runner.get_state(wid)
        return _json_dumps({"ok": True, "workflow": state})

    def _handle_workflow_list(self, limit: int = 20) -> str:
        runner = WorkflowRunner(self._workspace_root)
        rows = runner.list_states(limit=limit)
        return _json_dumps({"ok": True, "count": len(rows), "workflows": rows})

    def _handle_session_search(self, query: str, limit: int = 5) -> str:
        engine = SessionRecallEngine(self._workspace_root)
        rows = engine.search(query=query, limit=limit)
        return _json_dumps(
            {
                "ok": True,
                "query": query,
                "count": len(rows),
                "sessions": rows,
            }
        )

    def _handle_session_recall(self, session_id: str, query: str = "", max_points: int = 6) -> str:
        engine = SessionRecallEngine(self._workspace_root)
        recalled = engine.recall(session_id=session_id, query=query, max_points=max_points)
        return _json_dumps(
            {
                "ok": True,
                "session": recalled,
            }
        )

    def _handle_web_rank(self, query: str, results_json: str, max_results: int = 10) -> str:
        rows = _parse_json_array(results_json, field="results_json")
        normalized = normalize_and_rank_sources(
            query=str(query or ""),
            items=[x for x in rows if isinstance(x, dict)],
        )
        cap = max(1, int(max_results or 10))
        top = normalized[:cap]
        return _json_dumps(
            {
                "ok": True,
                "query": query,
                "count": len(top),
                "results": top,
            }
        )

    def _handle_memory_search(self, query: str, limit: int = 5) -> str:
        rows = self._memory.search_memories(query=query, limit=limit)
        return _json_dumps({"ok": True, "query": query, "count": len(rows), "results": rows})

    def _handle_skill_manage(
        self,
        action: str,
        name: str | None = None,
        description: str | None = None,
        instructions: str | None = None,
        tags_json: str | None = None,
        objective: str | None = None,
        workflow_id: str | None = None,
        handoff_json: str | None = None,
        outcomes_json: str | None = None,
    ) -> str:
        act = (action or "").strip().lower()
        if act == "list":
            rows = self._skills.list()
            return _json_dumps({"ok": True, "action": "list", "count": len(rows), "skills": rows})

        skill_name = (name or "").strip()
        if not skill_name:
            return "Error: name is required for action create/read/delete/promote."

        if act == "create":
            if not (description or "").strip():
                return "Error: description is required for action=create."
            if not (instructions or "").strip():
                return "Error: instructions is required for action=create."
            tags: list[str] = []
            if tags_json:
                tags = [str(x) for x in _parse_json_array(tags_json, field="tags_json")]
            created = self._skills.create_or_update(
                name=skill_name,
                description=str(description),
                instructions=str(instructions),
                tags=tags,
                source="manual",
            )
            return _json_dumps({"ok": True, "action": "create", "skill": created})

        if act == "read":
            skill = self._skills.read(name=skill_name)
            return _json_dumps({"ok": True, "action": "read", "skill": skill})

        if act == "delete":
            removed = self._skills.delete(name=skill_name)
            return _json_dumps({"ok": True, "action": "delete", "result": removed})

        if act == "promote":
            if not (objective or "").strip():
                return "Error: objective is required for action=promote."
            if not (workflow_id or "").strip():
                return "Error: workflow_id is required for action=promote."
            handoff = _parse_json_object(handoff_json or "{}", field="handoff_json")
            outcomes = _parse_json_array(outcomes_json or "[]", field="outcomes_json")
            promoted = self._skills.promote_from_workflow(
                skill_name=skill_name,
                objective=str(objective),
                workflow_id=str(workflow_id),
                handoff=handoff,
                outcomes=[x for x in outcomes if isinstance(x, dict)],
            )
            return _json_dumps({"ok": True, "action": "promote", "skill": promoted})

        return "Error: action must be one of create, read, list, delete, promote."

    def _handle_checkpoint_create(
        self,
        name: str,
        summary: str = "",
        metadata_json: str | None = None,
    ) -> str:
        metadata = _parse_json_object(metadata_json, field="metadata_json") if metadata_json else {}
        path = self._checkpoints.create_named_checkpoint(name=name, summary=summary, metadata=metadata)
        append_audit_record(
            self._workspace_root,
            "assistant.checkpoint_created",
            {"name": name, "checkpoint": path},
        )
        append_assistant_event(
            self._workspace_root,
            make_assistant_event(
                family="checkpoint",
                name="named_checkpoint_created",
                payload={"name": name, "checkpoint": path},
            ),
        )
        return _json_dumps({"ok": True, "name": name, "checkpoint": path, "metadata": metadata})

    def _handle_insights(self) -> str:
        report = self._insights.generate()
        return _json_dumps({"ok": True, "insights": report})

    def _handle_meeting_prep(
        self,
        events_json: str | None = None,
        chat_channel: str = "general",
        send_email_digest: bool = False,
        digest_to: str = "",
    ) -> str:
        events: list[dict[str, Any]]
        if events_json:
            parsed = _parse_json_array(events_json, field="events_json")
            events = [x for x in parsed if isinstance(x, dict)]
        else:
            events = []

        calendar = CalendarConnector(events=events)
        notes = NoteConnector()
        chat = ChatConnector()
        email = EmailConnector()

        router = ConnectorRouter()
        router.register(calendar)
        router.register(notes)
        router.register(chat)
        router.register(email)

        summary = run_meeting_prep_routine(
            router,
            chat_channel=chat_channel,
            send_email_digest=bool(send_email_digest),
            digest_to=digest_to,
        )

        return _json_dumps(
            {
                "ok": True,
                "prepared_events": summary.prepared_events,
                "note_ids": summary.note_ids,
                "chat_messages_sent": summary.chat_messages_sent,
                "email_messages_sent": summary.email_messages_sent,
                "chat_messages": chat.messages,
                "sent_emails": email.sent,
            }
        )


EXTENSION = AssistantExtension()
