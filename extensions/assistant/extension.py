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
from cross_connector_routines import run_meeting_prep_routine
from planner import PlanStep, WorkflowPlan
from profile import UserProfile
from workflow_runner import WorkflowRunner


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

    def on_load(self, context: ExtensionContext) -> None:
        self._ext_context = context
        agent_cfg = getattr(context, "_agent_config", None)
        if agent_cfg and getattr(agent_cfg, "workspace_root", None):
            self._workspace_root = str(agent_cfg.workspace_root)

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
                        description="dry_run or enqueue_prompts.",
                        enum=["dry_run", "enqueue_prompts"],
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
            "- assistant_plan_validate\n"
            "- assistant_workflow_run\n"
            "- assistant_meeting_prep\n"
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
            if not step_id:
                raise ValueError(f"steps_json[{idx}].id is required.")
            if not title:
                raise ValueError(f"steps_json[{idx}].title is required.")
            if not isinstance(depends_on, list):
                raise ValueError(f"steps_json[{idx}].depends_on must be a list.")
            steps.append(
                PlanStep(
                    id=step_id,
                    title=title,
                    depends_on=[str(x) for x in depends_on],
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

    def _handle_workflow_run(
        self,
        objective: str,
        steps_json: str,
        workflow_id: str | None = None,
        execution_mode: str = "dry_run",
    ) -> str:
        mode = (execution_mode or "dry_run").strip()
        if mode not in {"dry_run", "enqueue_prompts"}:
            return "Error: execution_mode must be one of: dry_run, enqueue_prompts."

        plan = self._build_plan(objective=objective, steps_json=steps_json, workflow_id=workflow_id)
        runner = WorkflowRunner(self._workspace_root)

        def _execute_step(step_id: str) -> str:
            if mode == "enqueue_prompts" and self._ext_context is not None:
                self._ext_context.enqueue(
                    (
                        f"[assistant workflow {plan.id}] Execute step {step_id} for objective "
                        f"'{plan.objective}'."
                    )
                )
                return f"enqueued prompt for step {step_id}"
            return f"dry run completed step {step_id}"

        outcomes = runner.run(plan, execute_step=_execute_step)
        return _json_dumps(
            {
                "ok": True,
                "workflow_id": plan.id,
                "objective": plan.objective,
                "execution_mode": mode,
                "outcomes": outcomes,
            }
        )

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
