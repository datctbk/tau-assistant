from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import threading
from typing import Callable


@dataclass
class Routine:
    id: str
    title: str
    interval_minutes: int
    enabled: bool = True
    last_run: str | None = None


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
