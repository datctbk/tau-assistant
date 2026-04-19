from __future__ import annotations

from datetime import datetime
from typing import Any

from connector_router import ConnectorRouter
from routine_engine import Routine


def _default_action(connector: str) -> str:
    c = (connector or "").strip().lower()
    if c == "chat":
        return "post_message"
    if c == "email":
        return "send_email"
    if c == "note":
        return "save_note"
    raise ValueError(f"Unsupported delivery connector: {connector!r}")


class RoutineDeliveryRunner:
    """Maps due routines to connector actions and dispatches delivery."""

    def __init__(self, router: ConnectorRouter) -> None:
        self.router = router

    def _build_payload(self, routine: Routine, *, now: datetime) -> tuple[str, dict[str, object]]:
        connector = (routine.delivery_connector or "chat").strip().lower()
        action = _default_action(connector)
        message = (
            routine.delivery_template.strip()
            if routine.delivery_template.strip()
            else f"[routine] {routine.title} is due at {now.isoformat()}"
        )
        message = (
            message.replace("{routine_id}", routine.id)
            .replace("{routine_title}", routine.title)
            .replace("{timestamp}", now.isoformat())
        )
        target = (routine.delivery_target or "").strip()

        if connector == "chat":
            return action, {"channel": target or "general", "text": message}
        if connector == "email":
            if not target:
                raise ValueError(f"Routine {routine.id}: delivery_target is required for email connector.")
            return action, {"to": target, "subject": f"Routine due: {routine.title}", "body": message}
        if connector == "note":
            note_id = target or f"routine-{routine.id}-{now.strftime('%Y%m%d-%H%M%S')}"
            return action, {"id": note_id, "body": message}
        raise ValueError(f"Unsupported delivery connector: {connector!r}")

    def deliver(self, routine: Routine) -> dict[str, Any]:
        now = datetime.now().astimezone()
        connector = (routine.delivery_connector or "chat").strip().lower()
        action, payload = self._build_payload(routine, now=now)
        resp = self.router.route(connector, action, payload)
        if not resp.ok:
            raise ValueError(f"Routine {routine.id}: delivery failed via {connector}.{action}: {resp.error}")
        return {
            "routine_id": routine.id,
            "title": routine.title,
            "connector": connector,
            "action": action,
            "payload": payload,
            "delivered_at": now.isoformat(),
            "timezone": str(now.tzinfo or ""),
            "response": resp.data,
        }
