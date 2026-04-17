from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol


@dataclass
class ConnectorRequest:
    action: str
    payload: dict[str, object] = field(default_factory=dict)


@dataclass
class ConnectorResponse:
    ok: bool
    data: dict[str, object] = field(default_factory=dict)
    error: str = ""


class Connector(Protocol):
    name: str

    def handle(self, request: ConnectorRequest) -> ConnectorResponse:
        ...


@dataclass
class CalendarConnector:
    name: str = "calendar"
    events: list[dict[str, object]] = field(default_factory=list)

    def handle(self, request: ConnectorRequest) -> ConnectorResponse:
        if request.action == "list_events":
            return ConnectorResponse(ok=True, data={"events": list(self.events)})

        if request.action == "add_event":
            ev = {
                "id": str(request.payload.get("id", f"evt-{len(self.events) + 1}")),
                "title": str(request.payload.get("title", "Untitled event")),
                "start": str(
                    request.payload.get("start", datetime.now(timezone.utc).isoformat())
                ),
                "attendees": list(request.payload.get("attendees", [])),
            }
            self.events.append(ev)
            return ConnectorResponse(ok=True, data={"event": ev})

        return ConnectorResponse(ok=False, error=f"Unsupported action {request.action!r}")


@dataclass
class EmailConnector:
    name: str = "email"
    sent: list[dict[str, object]] = field(default_factory=list)

    def handle(self, request: ConnectorRequest) -> ConnectorResponse:
        if request.action != "send_email":
            return ConnectorResponse(ok=False, error=f"Unsupported action {request.action!r}")

        msg = {
            "to": str(request.payload.get("to", "")),
            "subject": str(request.payload.get("subject", "")),
            "body": str(request.payload.get("body", "")),
        }
        self.sent.append(msg)
        return ConnectorResponse(ok=True, data={"message": msg})


@dataclass
class ChatConnector:
    name: str = "chat"
    messages: list[dict[str, object]] = field(default_factory=list)

    def handle(self, request: ConnectorRequest) -> ConnectorResponse:
        if request.action != "post_message":
            return ConnectorResponse(ok=False, error=f"Unsupported action {request.action!r}")

        msg = {
            "channel": str(request.payload.get("channel", "general")),
            "text": str(request.payload.get("text", "")),
        }
        self.messages.append(msg)
        return ConnectorResponse(ok=True, data={"message": msg})


@dataclass
class NoteConnector:
    name: str = "note"
    notes: dict[str, str] = field(default_factory=dict)

    def handle(self, request: ConnectorRequest) -> ConnectorResponse:
        if request.action == "save_note":
            key = str(request.payload.get("id", f"note-{len(self.notes) + 1}"))
            body = str(request.payload.get("body", ""))
            self.notes[key] = body
            return ConnectorResponse(ok=True, data={"id": key, "body": body})

        if request.action == "get_note":
            key = str(request.payload.get("id", ""))
            if key not in self.notes:
                return ConnectorResponse(ok=False, error=f"Unknown note {key!r}")
            return ConnectorResponse(ok=True, data={"id": key, "body": self.notes[key]})

        return ConnectorResponse(ok=False, error=f"Unsupported action {request.action!r}")