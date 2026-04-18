from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol
from urllib import error as urlerror
from urllib import request as urlrequest


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


def _remote_dispatch(
    connector_name: str,
    request: ConnectorRequest,
    *,
    timeout: float = 8.0,
    max_retries: int = 2,
) -> ConnectorResponse | None:
    """Dispatch connector action to optional remote API with auth/retry/rate-limit handling."""
    base = (
        os.getenv(f"TAU_ASSISTANT_{connector_name.upper()}_BASE_URL", "").strip()
        or os.getenv("TAU_ASSISTANT_CONNECTOR_BASE_URL", "").strip()
    )
    if not base:
        return None

    token = os.getenv(f"TAU_ASSISTANT_{connector_name.upper()}_TOKEN", "").strip()
    endpoint = f"{base.rstrip('/')}/{request.action}"
    payload = json.dumps(request.payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    attempts = max(1, int(max_retries) + 1)
    last_error = ""
    for attempt in range(1, attempts + 1):
        req = urlrequest.Request(endpoint, data=payload, headers=headers, method="POST")
        try:
            with urlrequest.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                try:
                    obj = json.loads(raw) if raw.strip() else {}
                except Exception:
                    obj = {"raw": raw}
                if isinstance(obj, dict):
                    ok = bool(obj.get("ok", True))
                    data = obj.get("data", obj)
                    err = str(obj.get("error", ""))
                    return ConnectorResponse(ok=ok, data=data if isinstance(data, dict) else {"value": data}, error=err)
                return ConnectorResponse(ok=True, data={"value": obj})
        except urlerror.HTTPError as exc:
            last_error = f"http {exc.code}"
            if exc.code == 429 and attempt < attempts:
                retry_after = 1.0
                try:
                    retry_after = float(exc.headers.get("Retry-After", "1"))
                except Exception:
                    retry_after = 1.0
                time.sleep(max(0.2, retry_after))
                continue
            if attempt < attempts and 500 <= int(exc.code) < 600:
                time.sleep(0.25 * attempt)
                continue
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            if attempt < attempts:
                time.sleep(0.25 * attempt)
                continue
    return ConnectorResponse(ok=False, error=f"Remote connector failure for {connector_name}.{request.action}: {last_error}")


@dataclass
class CalendarConnector:
    name: str = "calendar"
    events: list[dict[str, object]] = field(default_factory=list)

    def handle(self, request: ConnectorRequest) -> ConnectorResponse:
        remote = _remote_dispatch(self.name, request)
        if remote is not None:
            return remote
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
        remote = _remote_dispatch(self.name, request)
        if remote is not None:
            return remote
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
        remote = _remote_dispatch(self.name, request)
        if remote is not None:
            return remote
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
        remote = _remote_dispatch(self.name, request)
        if remote is not None:
            return remote
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
