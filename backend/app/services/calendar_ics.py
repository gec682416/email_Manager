from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.models import ExtractedEvent


def write_internal_calendar(db: Session, user_id: int) -> str:
    events = (
        db.query(ExtractedEvent)
        .filter(ExtractedEvent.user_id == user_id)
        .filter(ExtractedEvent.start_time.isnot(None))
        .filter(ExtractedEvent.status.in_(["draft", "confirmed", "conflict", "needs_review"]))
        .order_by(ExtractedEvent.start_time.asc())
        .all()
    )
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Email Manager Agent//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for event in events:
        lines.extend(_event_lines(event))
    lines.append("END:VCALENDAR")
    path = settings.calendar_path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    tmp.replace(path)
    return str(path)


def _event_lines(event: ExtractedEvent) -> list[str]:
    now = _format_dt(datetime.now(timezone.utc))
    start = _format_dt(event.start_time)
    end = _format_dt(event.end_time or event.start_time)
    description = event.description or ""
    if event.meeting_link:
        description = f"{description}\\n会议链接: {event.meeting_link}".strip()
    return [
        "BEGIN:VEVENT",
        f"UID:event-{event.id}@email-manager",
        f"DTSTAMP:{now}",
        f"DTSTART:{start}",
        f"DTEND:{end}",
        f"SUMMARY:{_escape(event.title)}",
        f"DESCRIPTION:{_escape(description)}",
        f"LOCATION:{_escape(event.location or '')}",
        f"STATUS:{'CONFIRMED' if event.status == 'confirmed' else 'TENTATIVE'}",
        "END:VEVENT",
    ]


def _format_dt(value: datetime | None) -> str:
    if value is None:
        value = datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
