from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


TOKEN_RE = re.compile(r"[a-z0-9]{2,}")


def _tokenize(text: str) -> set[str]:
    return set(TOKEN_RE.findall((text or "").lower()))


def _safe_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                txt = str(item.get("text", "")).strip()
                if txt:
                    parts.append(txt)
                continue
            parts.append(str(item))
        return "\n".join(parts).strip()
    return str(value or "")


class SessionRecallEngine:
    """Searches tau session files and builds deterministic recall summaries."""

    def __init__(self, workspace_root: str) -> None:
        self.workspace_root = workspace_root

    def _session_dirs(self) -> list[Path]:
        local = Path(self.workspace_root) / ".tau" / "sessions"
        home = Path.home() / ".tau" / "sessions"
        out: list[Path] = []
        if local.exists():
            out.append(local)
        if home.exists() and home != local:
            out.append(home)
        return out

    def _iter_session_files(self) -> list[Path]:
        rows: list[Path] = []
        for d in self._session_dirs():
            rows.extend(d.glob("*.json"))
        rows.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return rows

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any] | None:
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(obj, dict):
                return obj
        except Exception:
            return None
        return None

    @staticmethod
    def _message_text(msg: dict[str, Any]) -> str:
        return _safe_text(msg.get("content", ""))

    @staticmethod
    def _message_score(query_tokens: set[str], msg: dict[str, Any]) -> int:
        if not query_tokens:
            return 0
        txt = SessionRecallEngine._message_text(msg)
        mt = _tokenize(txt)
        overlap = len(query_tokens & mt)
        if overlap == 0:
            return 0
        role = str(msg.get("role", "")).strip().lower()
        role_weight = 2 if role == "user" else 1
        return overlap * role_weight

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        q_tokens = _tokenize(query)
        rows: list[dict[str, Any]] = []
        for path in self._iter_session_files():
            obj = self._load_json(path)
            if not obj:
                continue
            messages = [m for m in obj.get("messages", []) if isinstance(m, dict)]
            if not messages:
                continue
            per_scores = [self._message_score(q_tokens, m) for m in messages]
            total = sum(per_scores)
            best = max(per_scores) if per_scores else 0
            if q_tokens and total <= 0:
                continue
            top_indices = sorted(
                range(len(messages)),
                key=lambda i: per_scores[i],
                reverse=True,
            )[:3]
            snippets: list[str] = []
            for i in top_indices:
                if per_scores[i] <= 0 and q_tokens:
                    continue
                role = str(messages[i].get("role", "unknown")).strip().lower()
                txt = self._message_text(messages[i]).replace("\n", " ").strip()
                if txt:
                    snippets.append(f"{role}: {txt[:160]}")
            rows.append(
                {
                    "session_id": str(obj.get("id", path.stem)),
                    "name": str(obj.get("name", "")),
                    "updated_at": str(obj.get("updated_at", "")),
                    "model": str(obj.get("config", {}).get("model", "")),
                    "provider": str(obj.get("config", {}).get("provider", "")),
                    "message_count": len(messages),
                    "score": int((best * 100) + total),
                    "snippets": snippets,
                    "path": str(path),
                }
            )
        rows.sort(key=lambda x: (int(x.get("score", 0)), str(x.get("updated_at", ""))), reverse=True)
        return rows[: max(1, int(limit))]

    def _resolve_session_file(self, session_id: str) -> Path:
        sid = (session_id or "").strip()
        if not sid:
            raise ValueError("session_id is required.")
        matches: list[Path] = []
        for p in self._iter_session_files():
            stem = p.stem
            if stem == sid or stem.startswith(sid):
                matches.append(p)
        if not matches:
            raise ValueError(f"Session {sid!r} not found.")
        if len(matches) > 1:
            raise ValueError(f"Ambiguous session prefix {sid!r}; provide more characters.")
        return matches[0]

    def recall(self, session_id: str, query: str = "", max_points: int = 6) -> dict[str, Any]:
        path = self._resolve_session_file(session_id)
        obj = self._load_json(path)
        if not obj:
            raise ValueError(f"Could not parse session file: {path}")
        messages = [m for m in obj.get("messages", []) if isinstance(m, dict)]
        q_tokens = _tokenize(query)
        if q_tokens:
            scored = [
                (self._message_score(q_tokens, m), i, m)
                for i, m in enumerate(messages)
            ]
            scored = [x for x in scored if x[0] > 0]
            scored.sort(key=lambda x: x[0], reverse=True)
            selected = [m for _, _, m in scored[: max(1, int(max_points))]]
        else:
            selected = [m for m in messages if str(m.get("role", "")).lower() in {"user", "assistant"}]
            selected = selected[-max(1, int(max_points)) :]

        points: list[str] = []
        for m in selected:
            role = str(m.get("role", "unknown")).strip().lower()
            txt = self._message_text(m).replace("\n", " ").strip()
            if not txt:
                continue
            points.append(f"- {role}: {txt[:220]}")

        focus = query.strip() or "latest session context"
        name = str(obj.get("name", "")).strip() or "(unnamed)"
        summary_lines = [
            f"Session {str(obj.get('id', path.stem))[:8]} ({name})",
            f"Focus: {focus}",
            "",
            "Key points:",
        ]
        if points:
            summary_lines.extend(points)
        else:
            summary_lines.append("- No matching content found.")
        return {
            "session_id": str(obj.get("id", path.stem)),
            "name": name,
            "updated_at": str(obj.get("updated_at", "")),
            "message_count": len(messages),
            "focus": focus,
            "points": points,
            "summary_text": "\n".join(summary_lines).strip(),
            "path": str(path),
        }
