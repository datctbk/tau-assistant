from __future__ import annotations

from connector_router import ConnectorRouter
from connectors import (
    CalendarConnector,
    ChatConnector,
    ConnectorRequest,
    EmailConnector,
    NoteConnector,
)
from cross_connector_routines import run_meeting_prep_routine


def test_connector_router_register_and_route():
    router = ConnectorRouter()
    router.register(NoteConnector())

    assert router.has("note")
    resp = router.route("note", "save_note", {"id": "n1", "body": "hello"})
    assert resp.ok
    assert resp.data["id"] == "n1"


def test_meeting_prep_cross_connector_routine():
    calendar = CalendarConnector(
        events=[
            {
                "id": "evt-1",
                "title": "Weekly Planning",
                "start": "2026-04-16T09:00:00+00:00",
                "attendees": ["alice", "bob"],
            }
        ]
    )
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
        chat_channel="team-ops",
        send_email_digest=True,
        digest_to="lead@example.com",
    )

    assert summary.prepared_events == 1
    assert summary.chat_messages_sent == 1
    assert summary.email_messages_sent == 1
    assert summary.note_ids == ["meeting-prep-evt-1"]

    note = notes.handle(ConnectorRequest(action="get_note", payload={"id": "meeting-prep-evt-1"}))
    assert note.ok
    assert "Weekly Planning" in str(note.data.get("body", ""))


def test_meeting_prep_digest_requires_recipient():
    router = ConnectorRouter()
    router.register(CalendarConnector(events=[{"id": "evt-1", "title": "Demo"}]))
    router.register(NoteConnector())
    router.register(ChatConnector())
    router.register(EmailConnector())

    try:
        run_meeting_prep_routine(router, send_email_digest=True, digest_to="")
        assert False, "Expected digest recipient validation error"
    except ValueError as exc:
        assert "digest_to" in str(exc)
