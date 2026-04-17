from __future__ import annotations

from dataclasses import dataclass

from connector_router import ConnectorRouter


@dataclass
class MeetingPrepSummary:
    prepared_events: int
    note_ids: list[str]
    chat_messages_sent: int
    email_messages_sent: int


def run_meeting_prep_routine(
    router: ConnectorRouter,
    *,
    chat_channel: str = "general",
    send_email_digest: bool = False,
    digest_to: str = "",
) -> MeetingPrepSummary:
    """Cross-connector routine: calendar -> notes + chat (+ optional email)."""

    cal = router.route("calendar", "list_events")
    if not cal.ok:
        raise ValueError(f"calendar.list_events failed: {cal.error}")

    events = list(cal.data.get("events", []))
    note_ids: list[str] = []
    chat_sent = 0

    for event in events:
        event_id = str(event.get("id", ""))
        title = str(event.get("title", "Untitled event"))
        start = str(event.get("start", ""))
        attendees = ", ".join(str(a) for a in event.get("attendees", []))

        note_body = (
            f"# Meeting Prep: {title}\n"
            f"Start: {start}\n"
            f"Attendees: {attendees or 'n/a'}\n\n"
            "Agenda\n"
            "- Objective\n"
            "- Risks\n"
            "- Decisions needed\n"
        )
        note_id = f"meeting-prep-{event_id or len(note_ids) + 1}"
        save = router.route("note", "save_note", {"id": note_id, "body": note_body})
        if not save.ok:
            raise ValueError(f"note.save_note failed: {save.error}")
        note_ids.append(note_id)

        msg = router.route(
            "chat",
            "post_message",
            {
                "channel": chat_channel,
                "text": f"Prep note ready for '{title}': {note_id}",
            },
        )
        if not msg.ok:
            raise ValueError(f"chat.post_message failed: {msg.error}")
        chat_sent += 1

    email_sent = 0
    if send_email_digest and events:
        if not digest_to:
            raise ValueError("digest_to is required when send_email_digest=True")
        titles = ", ".join(str(ev.get("title", "Untitled event")) for ev in events)
        email = router.route(
            "email",
            "send_email",
            {
                "to": digest_to,
                "subject": "Meeting prep digest",
                "body": f"Prepared {len(events)} meetings: {titles}",
            },
        )
        if not email.ok:
            raise ValueError(f"email.send_email failed: {email.error}")
        email_sent = 1

    return MeetingPrepSummary(
        prepared_events=len(events),
        note_ids=note_ids,
        chat_messages_sent=chat_sent,
        email_messages_sent=email_sent,
    )
