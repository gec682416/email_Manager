from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import (
    AgentRun,
    EmailMessage,
    EventConflict,
    ExtractedEvent,
    MailAccount,
    Reminder,
    Task,
)
from app.schemas import (
    AgentRunOut,
    AgentAnswer,
    AgentQuery,
    DashboardOut,
    EmailDetail,
    EmailOut,
    EventConflictOut,
    EventOut,
    EventUpdate,
    MailAccountCreate,
    MailAccountOut,
    ReminderOut,
    SyncResult,
    TaskOut,
)
from app.services.agent import answer_question
from app.services.calendar_ics import write_internal_calendar
from app.services.conflicts import close_conflicts_for_event, detect_conflicts_for_event, detect_conflicts_for_user, open_conflicts_for_event
from app.services.json_utils import loads_list
from app.services.lifecycle import cleanup_expired_raw_copies, delete_local_email_copy
from app.services.pipeline import sync_mail_account
from app.services.storage import read_text_ref
from app.services.users import get_or_create_local_user


router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db)):
    user = get_or_create_local_user(db)
    account = db.query(MailAccount).filter(MailAccount.user_id == user.id).order_by(MailAccount.last_sync_at.desc()).first()
    events = db.query(ExtractedEvent).filter(ExtractedEvent.user_id == user.id).order_by(ExtractedEvent.start_time.asc()).limit(8).all()
    reminders = db.query(Reminder).filter(Reminder.user_id == user.id).order_by(Reminder.remind_at.asc()).limit(8).all()
    return DashboardOut(
        last_sync_at=account.last_sync_at if account else None,
        email_count=db.query(EmailMessage).filter(EmailMessage.user_id == user.id).count(),
        event_count=db.query(ExtractedEvent).filter(ExtractedEvent.user_id == user.id).count(),
        task_count=db.query(Task).filter(Task.user_id == user.id).count(),
        conflict_count=db.query(EventConflict).filter(EventConflict.user_id == user.id).filter(EventConflict.status == "open").count(),
        pending_review_count=db.query(ExtractedEvent).filter(ExtractedEvent.user_id == user.id).filter(ExtractedEvent.status == "needs_review").count(),
        upcoming_events=[_event_out(db, e) for e in events],
        reminders=[ReminderOut.model_validate(r) for r in reminders],
    )


@router.post("/mail-accounts", response_model=MailAccountOut)
def create_mail_account(payload: MailAccountCreate, db: Session = Depends(get_db)):
    user = get_or_create_local_user(db)
    existing = db.query(MailAccount).filter(MailAccount.user_id == user.id).filter(MailAccount.email_address == payload.email_address).first()
    if existing:
        existing.encrypted_app_password = payload.app_password
        existing.imap_host = payload.imap_host
        existing.imap_port = payload.imap_port
        db.commit()
        db.refresh(existing)
        return existing
    account = MailAccount(
        user_id=user.id,
        provider="netease",
        email_address=str(payload.email_address),
        imap_host=payload.imap_host,
        imap_port=payload.imap_port,
        encrypted_app_password=payload.app_password,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@router.get("/mail-accounts", response_model=list[MailAccountOut])
def list_mail_accounts(db: Session = Depends(get_db)):
    user = get_or_create_local_user(db)
    return db.query(MailAccount).filter(MailAccount.user_id == user.id).all()


@router.post("/mail-accounts/{account_id}/sync", response_model=SyncResult)
def sync_account(account_id: int, db: Session = Depends(get_db)):
    account = db.get(MailAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="mail account not found")
    try:
        result = sync_mail_account(db, account_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"同步失败：{exc}") from exc
    return SyncResult(account_id=account_id, fetched=int(result["fetched"]), processed=int(result["processed"]), message=str(result["message"]))


@router.get("/emails", response_model=list[EmailOut])
def list_emails(category: str | None = None, limit: int = 50, db: Session = Depends(get_db)):
    user = get_or_create_local_user(db)
    query = db.query(EmailMessage).filter(EmailMessage.user_id == user.id).filter(EmailMessage.local_deleted_at.is_(None)).order_by(EmailMessage.received_at.desc())
    emails = query.limit(min(limit, 200)).all()
    out: list[EmailOut] = []
    for email in emails:
        if category and (not email.classification or email.classification.category != category):
            continue
        out.append(_email_out(email))
    return out


@router.get("/emails/{email_id}", response_model=EmailDetail)
def get_email(email_id: int, db: Session = Depends(get_db)):
    email = db.get(EmailMessage, email_id)
    if not email or email.local_deleted_at is not None:
        raise HTTPException(status_code=404, detail="email not found")
    base = _email_out(email)
    parsed = email.parsed
    return EmailDetail(
        **base.model_dump(),
        clean_text=parsed.clean_text if parsed else read_text_ref(email.text_ref),
        links=loads_list(parsed.links_json if parsed else None),
        evidence=loads_list(email.classification.evidence_json if email.classification else None),
    )


@router.delete("/emails/{email_id}/local-copy")
def delete_email_local_copy(email_id: int, db: Session = Depends(get_db)):
    user = get_or_create_local_user(db)
    email = db.get(EmailMessage, email_id)
    if not email or email.user_id != user.id:
        raise HTTPException(status_code=404, detail="email not found")
    return delete_local_email_copy(db, email)


@router.get("/events", response_model=list[EventOut])
def list_events(db: Session = Depends(get_db)):
    user = get_or_create_local_user(db)
    events = db.query(ExtractedEvent).filter(ExtractedEvent.user_id == user.id).order_by(ExtractedEvent.start_time.asc()).all()
    return [_event_out(db, event) for event in events]


@router.patch("/events/{event_id}", response_model=EventOut)
def update_event(event_id: int, payload: EventUpdate, db: Session = Depends(get_db)):
    user = get_or_create_local_user(db)
    event = db.get(ExtractedEvent, event_id)
    if not event or event.user_id != user.id:
        raise HTTPException(status_code=404, detail="event not found")
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        if value is not None:
            setattr(event, field, value)
    db.commit()
    db.refresh(event)
    detect_conflicts_for_event(db, event)
    write_internal_calendar(db, event.user_id)
    return _event_out(db, event)


@router.patch("/events/{event_id}/confirm", response_model=EventOut)
def confirm_event(event_id: int, db: Session = Depends(get_db)):
    event = db.get(ExtractedEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="event not found")
    event.status = "confirmed"
    db.commit()
    db.refresh(event)
    detect_conflicts_for_event(db, event)
    write_internal_calendar(db, event.user_id)
    return _event_out(db, event)


@router.patch("/events/{event_id}/ignore", response_model=EventOut)
def ignore_event(event_id: int, db: Session = Depends(get_db)):
    event = db.get(ExtractedEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="event not found")
    event.status = "ignored"
    db.commit()
    db.refresh(event)
    close_conflicts_for_event(db, event.id)
    write_internal_calendar(db, event.user_id)
    return _event_out(db, event)


@router.get("/conflicts", response_model=list[EventConflictOut])
def list_conflicts(db: Session = Depends(get_db)):
    user = get_or_create_local_user(db)
    return db.query(EventConflict).filter(EventConflict.user_id == user.id).filter(EventConflict.status == "open").order_by(EventConflict.created_at.desc()).all()


@router.post("/conflicts/recheck")
def recheck_conflicts(db: Session = Depends(get_db)):
    user = get_or_create_local_user(db)
    count = detect_conflicts_for_user(db, user.id)
    return {"open_conflicts_checked": count}


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(db: Session = Depends(get_db)):
    user = get_or_create_local_user(db)
    return db.query(Task).filter(Task.user_id == user.id).order_by(Task.due_at.asc()).all()


@router.get("/reminders", response_model=list[ReminderOut])
def list_reminders(db: Session = Depends(get_db)):
    user = get_or_create_local_user(db)
    return db.query(Reminder).filter(Reminder.user_id == user.id).order_by(Reminder.remind_at.asc()).all()


@router.get("/calendar.ics")
def download_calendar(db: Session = Depends(get_db)):
    user = get_or_create_local_user(db)
    path = Path(write_internal_calendar(db, user.id))
    return FileResponse(path, media_type="text/calendar", filename="internal_calendar.ics")


@router.post("/agent/query", response_model=AgentAnswer)
def agent_query(payload: AgentQuery, db: Session = Depends(get_db)):
    user = get_or_create_local_user(db)
    result = answer_question(db, user.id, payload.question)
    return AgentAnswer(
        answer=result.answer,
        source_refs=result.source_refs,
        last_sync_at=result.last_sync_at,
        run_id=result.run_id,
        model_name=result.model_name,
        tool_trace=result.tool_trace,
    )


@router.get("/agent-runs/{run_id}", response_model=AgentRunOut)
def get_agent_run(run_id: int, db: Session = Depends(get_db)):
    user = get_or_create_local_user(db)
    run = db.get(AgentRun, run_id)
    if not run or run.user_id != user.id:
        raise HTTPException(status_code=404, detail="agent run not found")
    events = []
    if run.jsonl_ref:
        path = Path(run.jsonl_ref)
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    events.append({"type": "invalid_log_line", "raw": line[:500]})
    return AgentRunOut(
        id=run.id,
        run_type=run.run_type,
        status=run.status,
        input_text=run.input_text,
        output_text=run.output_text,
        summary=run.summary,
        model_name=run.model_name,
        jsonl_ref=run.jsonl_ref,
        events=events,
        created_at=run.created_at,
    )


@router.post("/maintenance/cleanup-raw")
def cleanup_raw(db: Session = Depends(get_db)):
    return cleanup_expired_raw_copies(db)


def _email_out(email: EmailMessage) -> EmailOut:
    return EmailOut(
        id=email.id,
        subject=email.subject,
        from_name=email.from_name,
        from_email=email.from_email,
        sent_at=email.sent_at,
        received_at=email.received_at,
        snippet=email.snippet,
        category=email.classification.category if email.classification else None,
        confidence=email.classification.confidence if email.classification else None,
    )


def _event_out(db: Session, event: ExtractedEvent) -> EventOut:
    conflicts = [
        {
            "id": conflict.id,
            "conflict_event_id": conflict.conflict_event_id,
            "conflict_type": conflict.conflict_type,
            "severity": conflict.severity,
            "description": conflict.description,
            "status": conflict.status,
        }
        for conflict in open_conflicts_for_event(db, event.id)
    ]
    return EventOut(
        id=event.id,
        source_email_id=event.source_email_id,
        event_type=event.event_type,
        title=event.title,
        company=event.company,
        description=event.description,
        start_time=event.start_time,
        end_time=event.end_time,
        timezone=event.timezone,
        location=event.location,
        meeting_link=event.meeting_link,
        confidence=event.confidence,
        status=event.status,
        missing_fields=loads_list(event.missing_fields_json),
        evidence=loads_list(event.evidence_json),
        conflicts=conflicts,
    )
