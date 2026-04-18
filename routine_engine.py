from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
import threading
from typing import Callable


@dataclass
class Routine:
    id: str
    title: str
    interval_minutes: int
    enabled: bool = True
    last_run: str | None = None
    delivery_connector: str = "chat"
    delivery_target: str = ""
    delivery_template: str = ""


@dataclass
class RoutineEngine:
    routines: list[Routine] = field(default_factory=list)
    _scheduler_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _scheduler_stop: threading.Event = field(default_factory=threading.Event, init=False, repr=False)

    def due_routines(self, now: datetime | None = None) -> list[Routine]:
        now = now or datetime.now(timezone.utc)
        due: list[Routine] = []
        for r in self.routines:
            if not r.enabled:
                continue
            if r.last_run is None:
                due.append(r)
                continue
            last = datetime.fromisoformat(r.last_run)
            if now - last >= timedelta(minutes=r.interval_minutes):
                due.append(r)
        return due

    def mark_run(self, routine_id: str, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        for r in self.routines:
            if r.id == routine_id:
                r.last_run = now.isoformat()
                return
        raise ValueError(f"Routine {routine_id!r} not found")

    def upsert(self, routine: Routine) -> Routine:
        rid = routine.id.strip()
        if not rid:
            raise ValueError("Routine id is required.")
        for idx, existing in enumerate(self.routines):
            if existing.id == rid:
                self.routines[idx] = routine
                return routine
        self.routines.append(routine)
        return routine

    def delete(self, routine_id: str) -> bool:
        rid = routine_id.strip()
        for idx, existing in enumerate(self.routines):
            if existing.id == rid:
                del self.routines[idx]
                return True
        return False

    def start_scheduler(
        self,
        *,
        on_due: Callable[[Routine], None],
        poll_interval_seconds: float = 5.0,
    ) -> None:
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            return
        self._scheduler_stop.clear()

        def _loop() -> None:
            while not self._scheduler_stop.is_set():
                now = datetime.now(timezone.utc)
                for routine in self.due_routines(now):
                    try:
                        on_due(routine)
                        self.mark_run(routine.id, now)
                    except Exception:  # noqa: BLE001
                        # Keep scheduler resilient; individual callback failures should not crash loop.
                        pass
                self._scheduler_stop.wait(max(0.1, poll_interval_seconds))

        self._scheduler_thread = threading.Thread(target=_loop, name="TauRoutineScheduler", daemon=True)
        self._scheduler_thread.start()

    def stop_scheduler(self, timeout: float = 2.0) -> None:
        self._scheduler_stop.set()
        if self._scheduler_thread is not None:
            self._scheduler_thread.join(timeout=timeout)

    def save(self, path: str) -> str:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "routines": [asdict(r) for r in self.routines],
        }
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(target)

    @classmethod
    def load(cls, path: str) -> "RoutineEngine":
        target = Path(path)
        if not target.exists():
            return cls(routines=[])
        raw = json.loads(target.read_text(encoding="utf-8"))
        items = raw.get("routines", [])
        rows: list[Routine] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                rows.append(
                    Routine(
                        id=str(item.get("id", "")),
                        title=str(item.get("title", "")),
                        interval_minutes=int(item.get("interval_minutes", 60)),
                        enabled=bool(item.get("enabled", True)),
                        last_run=str(item.get("last_run")) if item.get("last_run") else None,
                        delivery_connector=str(item.get("delivery_connector", "chat") or "chat"),
                        delivery_target=str(item.get("delivery_target", "") or ""),
                        delivery_template=str(item.get("delivery_template", "") or ""),
                    )
                )
            except Exception:  # noqa: BLE001
                continue
        return cls(routines=rows)

    @staticmethod
    def workspace_path(workspace_root: str) -> Path:
        return Path(workspace_root) / ".tau" / "assistant" / "routines.json"

    def save_workspace(self, workspace_root: str) -> str:
        return self.save(str(self.workspace_path(workspace_root)))

    @classmethod
    def load_workspace(cls, workspace_root: str) -> "RoutineEngine":
        return cls.load(str(cls.workspace_path(workspace_root)))
