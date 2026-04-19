from __future__ import annotations

from connector_router import ConnectorRouter
from connectors import ChatConnector, EmailConnector, NoteConnector
from routine_delivery import RoutineDeliveryRunner
from routine_engine import Routine


def _router() -> ConnectorRouter:
    router = ConnectorRouter()
    router.register(ChatConnector())
    router.register(EmailConnector())
    router.register(NoteConnector())
    return router


def test_routine_delivery_chat():
    runner = RoutineDeliveryRunner(_router())
    rec = runner.deliver(
        Routine(
            id="r1",
            title="Daily Brief",
            interval_minutes=60,
            delivery_connector="chat",
            delivery_target="team-ops",
            delivery_template="Run {routine_title} at {timestamp}",
        )
    )
    assert rec["connector"] == "chat"
    assert rec["payload"]["channel"] == "team-ops"
    assert rec["timezone"] != ""
    assert "Run Daily Brief at " in rec["payload"]["text"]


def test_routine_delivery_email_requires_target():
    runner = RoutineDeliveryRunner(_router())
    try:
        runner.deliver(
            Routine(
                id="r2",
                title="Digest",
                interval_minutes=60,
                delivery_connector="email",
                delivery_target="",
            )
        )
        assert False, "Expected validation failure for email delivery_target"
    except ValueError as exc:
        assert "delivery_target" in str(exc)
