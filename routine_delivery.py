from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any
from urllib import parse as urlparse
from urllib import request as urlrequest

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

    def _resolve_telegram_token(self) -> str:
        token = os.getenv("TAU_GATEWAY_TELEGRAM_TOKEN", "").strip()
        if token:
            return token
        cfg = Path.home() / ".tau" / "gateway.yaml"
        if not cfg.exists():
            return ""
        raw = cfg.read_text(encoding="utf-8")
        # Prefer YAML if available.
        try:
            import yaml  # type: ignore

            data = yaml.safe_load(raw) or {}
            token = (
                ((data.get("platforms", {}) or {}).get("telegram", {}) or {}).get("token", "")
            )
            if isinstance(token, str):
                return token.strip()
        except Exception:
            pass
        # JSON fallback for JSON-subset configs.
        try:
            data = json.loads(raw)
            token = (
                ((data.get("platforms", {}) or {}).get("telegram", {}) or {}).get("token", "")
            )
            if isinstance(token, str):
                return token.strip()
        except Exception:
            pass
        return ""

    def _deliver_telegram_direct(self, chat_id: str, text: str) -> dict[str, Any]:
        token = self._resolve_telegram_token()
        if not token:
            raise ValueError("Missing Telegram token. Set TAU_GATEWAY_TELEGRAM_TOKEN or ~/.tau/gateway.yaml")
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": int(chat_id), "text": text}
        data = urlparse.urlencode(payload).encode("utf-8")
        req = urlrequest.Request(url, data=data, method="POST")
        with urlrequest.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        obj = json.loads(body)
        if not obj.get("ok"):
            raise ValueError(f"Telegram API error: {obj}")
        return obj

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
        # Hybrid fix: if chat target is explicit telegram:<chat_id>, deliver to Telegram directly.
        if connector == "chat":
            channel = str(payload.get("channel", "")).strip()
            if channel.startswith("telegram:"):
                chat_id = channel.split(":", 1)[1].strip()
                if not chat_id:
                    raise ValueError(f"Routine {routine.id}: invalid telegram target {channel!r}")
                text = str(payload.get("text", ""))
                response = self._deliver_telegram_direct(chat_id, text)
                return {
                    "routine_id": routine.id,
                    "title": routine.title,
                    "connector": "telegram",
                    "action": "sendMessage",
                    "payload": {"channel": channel, "text": text},
                    "delivered_at": now.isoformat(),
                    "timezone": str(now.tzinfo or ""),
                    "response": response,
                }
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
