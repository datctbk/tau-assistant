from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from connector_router import ConnectorRouter
from connectors import CalendarConnector, ChatConnector, EmailConnector, NoteConnector
from cross_connector_routines import run_meeting_prep_routine
from planner import PlanStep, WorkflowPlan
from routine_engine import Routine, RoutineEngine
from workflow_runner import WorkflowRunner


def _parse_json(raw: str) -> Any:
    return json.loads(raw)


def _load_json_arg(raw: str | None, path: str | None, default: Any) -> Any:
    if raw:
        return _parse_json(raw)
    if path:
        return _parse_json(Path(path).read_text(encoding="utf-8"))
    return default


def _build_plan(objective: str, steps: list[dict[str, Any]], workflow_id: str) -> WorkflowPlan:
    plan_steps: list[PlanStep] = []
    for idx, row in enumerate(steps):
        sid = str(row.get("id", "")).strip()
        title = str(row.get("title", "")).strip()
        depends_on = row.get("depends_on", [])
        action = str(row.get("action", "noop")).strip() or "noop"
        connector = str(row.get("connector", "")).strip()
        connector_action = str(row.get("connector_action", "")).strip()
        payload = row.get("payload", {})
        retries = row.get("retries", 0)
        on_failure = str(row.get("on_failure", "stop")).strip().lower() or "stop"
        if not sid or not title:
            raise ValueError(f"Invalid step at index {idx}: id/title are required")
        if not isinstance(depends_on, list):
            raise ValueError(f"Invalid step at index {idx}: depends_on must be a list")
        if not isinstance(payload, dict):
            raise ValueError(f"Invalid step at index {idx}: payload must be an object")
        if on_failure not in {"stop", "continue"}:
            raise ValueError(f"Invalid step at index {idx}: on_failure must be stop|continue")
        try:
            retries_val = max(0, int(retries))
        except Exception as exc:
            raise ValueError(f"Invalid step at index {idx}: retries must be integer >= 0") from exc
        plan_steps.append(
            PlanStep(
                id=sid,
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
    return WorkflowPlan(id=workflow_id, objective=objective, steps=plan_steps)


def cmd_workflow(args: argparse.Namespace) -> int:
    steps = _load_json_arg(args.steps_json, args.steps_file, default=[])
    if not isinstance(steps, list):
        raise ValueError("steps must be a JSON array")
    plan = _build_plan(args.objective, steps, args.workflow_id)
    runner = WorkflowRunner(args.workspace, session_id=args.session_id)
    outcomes = runner.run(plan, execute_step=lambda sid: f"completed:{sid}")
    print(json.dumps({"workflow_id": plan.id, "outcomes": outcomes}, ensure_ascii=False, indent=2))
    return 0


def cmd_meeting_prep(args: argparse.Namespace) -> int:
    events = _load_json_arg(args.events_json, args.events_file, default=[])
    if not isinstance(events, list):
        raise ValueError("events must be a JSON array")

    router = ConnectorRouter()
    chat = ChatConnector()
    email = EmailConnector()
    router.register(CalendarConnector(events=[e for e in events if isinstance(e, dict)]))
    router.register(NoteConnector())
    router.register(chat)
    router.register(email)

    summary = run_meeting_prep_routine(
        router,
        chat_channel=args.chat_channel,
        send_email_digest=args.send_email_digest,
        digest_to=args.digest_to,
    )
    print(
        json.dumps(
            {
                "prepared_events": summary.prepared_events,
                "note_ids": summary.note_ids,
                "chat_messages_sent": summary.chat_messages_sent,
                "email_messages_sent": summary.email_messages_sent,
                "chat_messages": chat.messages,
                "sent_emails": email.sent,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_scheduler(args: argparse.Namespace) -> int:
    routines = _load_json_arg(args.routines_json, args.routines_file, default=[])
    if not isinstance(routines, list):
        raise ValueError("routines must be a JSON array")

    engine = RoutineEngine(
        routines=[
            Routine(
                id=str(item.get("id", "")),
                title=str(item.get("title", "")),
                interval_minutes=int(item.get("interval_minutes", 60)),
                enabled=bool(item.get("enabled", True)),
            )
            for item in routines
            if isinstance(item, dict)
        ]
    )

    def _on_due(routine: Routine) -> None:
        print(f"[due] {routine.id}: {routine.title}")

    engine.start_scheduler(on_due=_on_due, poll_interval_seconds=args.poll_interval)
    try:
        if args.duration_seconds > 0:
            time.sleep(args.duration_seconds)
        else:
            while True:
                time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        engine.stop_scheduler()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="tau-assistant optional CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_workflow = sub.add_parser("workflow", help="Run a workflow plan")
    p_workflow.add_argument("--workspace", default=".", help="Workspace root")
    p_workflow.add_argument("--session-id", default="", help="Optional session id for workflow events")
    p_workflow.add_argument("--workflow-id", default="assistant-workflow", help="Workflow id")
    p_workflow.add_argument("--objective", required=True, help="Workflow objective")
    p_workflow.add_argument("--steps-json", default=None, help="Workflow steps as JSON array")
    p_workflow.add_argument("--steps-file", default=None, help="Path to JSON file with workflow steps")
    p_workflow.set_defaults(func=cmd_workflow)

    p_prep = sub.add_parser("meeting-prep", help="Run meeting prep routine")
    p_prep.add_argument("--events-json", default=None, help="Calendar events as JSON array")
    p_prep.add_argument("--events-file", default=None, help="Path to JSON file with calendar events")
    p_prep.add_argument("--chat-channel", default="general", help="Target chat channel")
    p_prep.add_argument("--send-email-digest", action="store_true", help="Send digest email")
    p_prep.add_argument("--digest-to", default="", help="Digest email recipient")
    p_prep.set_defaults(func=cmd_meeting_prep)

    p_sched = sub.add_parser("scheduler", help="Run routine scheduler")
    p_sched.add_argument("--workspace", default=".", help="Workspace root (reserved for future use)")
    p_sched.add_argument("--session-id", default="", help="Optional session id (reserved for future use)")
    p_sched.add_argument("--routines-json", default=None, help="Routines as JSON array")
    p_sched.add_argument("--routines-file", default=None, help="Path to JSON file with routines")
    p_sched.add_argument("--poll-interval", type=float, default=5.0, help="Scheduler poll interval in seconds")
    p_sched.add_argument("--duration-seconds", type=float, default=30.0, help="Run duration; 0 means forever")
    p_sched.set_defaults(func=cmd_scheduler)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
