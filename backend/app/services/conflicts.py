from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import EventConflict, ExtractedEvent, Reminder
from app.services.json_utils import dumps


ACTIVE_EVENT_STATUSES = {"draft", "confirmed", "conflict", "needs_review"}


def detect_conflicts_for_event(db: Session, event: ExtractedEvent) -> list[EventConflict]:
    _close_existing_conflicts(db, event.id)
    if not event.start_time:
        conflict = _upsert_conflict(
            db,
            event,
            None,
            "ambiguous_time",
            "warning",
            f"{event.title} 缺少开始时间，需要人工确认。",
        )
        _ensure_conflict_reminder(db, event.user_id, conflict)
        return [conflict]

    start = event.start_time
    end = event.end_time or event.start_time + timedelta(hours=1)
    candidates = (
        db.query(ExtractedEvent)
        .filter(ExtractedEvent.user_id == event.user_id)
        .filter(ExtractedEvent.id != event.id)
        .filter(ExtractedEvent.status.in_(ACTIVE_EVENT_STATUSES))
        .filter(ExtractedEvent.start_time.isnot(None))
        .filter(
            or_(
                ExtractedEvent.end_time.is_(None),
                ExtractedEvent.end_time > start,
            )
        )
        .filter(ExtractedEvent.start_time < end)
        .all()
    )

    conflicts: list[EventConflict] = []
    for other in candidates:
        other_end = other.end_time or other.start_time + timedelta(hours=1)
        if _overlaps(start, end, other.start_time, other_end):
            conflict = _upsert_conflict(
                db,
                event,
                other,
                "hard_overlap",
                "critical",
                f"{event.title} 与 {other.title} 时间重叠。",
            )
            _upsert_conflict(
                db,
                other,
                event,
                "hard_overlap",
                "critical",
                f"{other.title} 与 {event.title} 时间重叠。",
            )
            conflicts.append(conflict)

    if conflicts and event.status in {"draft", "needs_review"}:
        event.status = "conflict"
        db.commit()
    return conflicts


def detect_conflicts_for_user(db: Session, user_id: int) -> int:
    events = (
        db.query(ExtractedEvent)
        .filter(ExtractedEvent.user_id == user_id)
        .filter(ExtractedEvent.status.in_(ACTIVE_EVENT_STATUSES))
        .all()
    )
    count = 0
    for event in events:
        count += len(detect_conflicts_for_event(db, event))
    return count


def open_conflicts_for_event(db: Session, event_id: int) -> list[EventConflict]:
    return (
        db.query(EventConflict)
        .filter(EventConflict.event_id == event_id)
        .filter(EventConflict.status == "open")
        .order_by(EventConflict.created_at.desc())
        .all()
    )


def open_conflicts_for_user(db: Session, user_id: int) -> list[EventConflict]:
    return (
        db.query(EventConflict)
        .filter(EventConflict.user_id == user_id)
        .filter(EventConflict.status == "open")
        .order_by(EventConflict.created_at.desc())
        .all()
    )


def close_conflicts_for_event(db: Session, event_id: int) -> None:
    for conflict in db.query(EventConflict).filter(EventConflict.event_id == event_id).filter(EventConflict.status == "open").all():
        conflict.status = "resolved"
    for conflict in db.query(EventConflict).filter(EventConflict.conflict_event_id == event_id).filter(EventConflict.status == "open").all():
        conflict.status = "resolved"
    db.commit()


def _upsert_conflict(
    db: Session,
    event: ExtractedEvent,
    other: ExtractedEvent | None,
    conflict_type: str,
    severity: str,
    description: str,
) -> EventConflict:
    query = (
        db.query(EventConflict)
        .filter(EventConflict.event_id == event.id)
        .filter(EventConflict.conflict_type == conflict_type)
        .filter(EventConflict.conflict_event_id == (other.id if other else None))
    )
    conflict = query.first()
    if conflict:
        conflict.severity = severity
        conflict.description = description
        conflict.status = "open"
    else:
        conflict = EventConflict(
            user_id=event.user_id,
            event_id=event.id,
            conflict_event_id=other.id if other else None,
            conflict_type=conflict_type,
            severity=severity,
            description=description,
        )
        db.add(conflict)
    db.commit()
    db.refresh(conflict)
    return conflict


def _close_existing_conflicts(db: Session, event_id: int) -> None:
    for conflict in db.query(EventConflict).filter(EventConflict.event_id == event_id).filter(EventConflict.status == "open").all():
        conflict.status = "resolved"
    db.commit()


def _ensure_conflict_reminder(db: Session, user_id: int, conflict: EventConflict) -> None:
    existing = (
        db.query(Reminder)
        .filter(Reminder.target_type == "conflict")
        .filter(Reminder.target_id == conflict.id)
        .first()
    )
    if existing:
        return
    db.add(
        Reminder(
            user_id=user_id,
            target_type="conflict",
            target_id=conflict.id,
            remind_at=datetime.now().astimezone(),
            payload_json=dumps({"description": conflict.description}),
        )
    )
    db.commit()


def _overlaps(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end
