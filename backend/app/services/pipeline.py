from __future__ import annotations

import imaplib
import re
from datetime import timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    EmailClassification,
    EmailMessage,
    EmailParsedContent,
    ExtractedEvent,
    MailAccount,
    MailboxSyncState,
    Reminder,
    Task,
    utcnow,
)
from app.services.calendar_ics import write_internal_calendar
from app.services.classifier import classify_email
from app.services.conflicts import detect_conflicts_for_event
from app.services.email_parser import (
    extract_body,
    extract_links,
    header_text,
    parse_address_list,
    parse_datetime,
    parse_message,
    parse_sender,
    snippet,
)
from app.services.extractor import extract_event, extract_task
from app.services.json_utils import dumps, loads_list
from app.services.storage import sha256_bytes, write_email_blob


def sync_mail_account(db: Session, account_id: int) -> dict[str, int | str]:
    account = db.get(MailAccount, account_id)
    if not account:
        raise ValueError("mail account not found")

    state = (
        db.query(MailboxSyncState)
        .filter(MailboxSyncState.mail_account_id == account.id)
        .filter(MailboxSyncState.folder == settings.netease_folder)
        .first()
    )
    if not state:
        state = MailboxSyncState(mail_account_id=account.id, folder=settings.netease_folder)
        db.add(state)
        db.commit()
        db.refresh(state)

    state.sync_status = "running"
    state.error_message = None
    db.commit()

    fetched = 0
    processed = 0
    max_uid = state.last_seen_uid or 0
    try:
        with imaplib.IMAP4_SSL(account.imap_host, account.imap_port) as client:
            client.login(account.email_address, account.encrypted_app_password)
            _send_imap_id(client, account.email_address)
            selected_folder = _select_mailbox(client, settings.netease_folder)
            criteria = f"UID {state.last_seen_uid + 1}:*" if state.last_seen_uid else "ALL"
            status, data = client.uid("search", None, criteria)
            if status != "OK":
                raise RuntimeError("IMAP search failed")
            uids = [int(uid) for uid in data[0].split() if uid]
            for uid in uids:
                existing = (
                    db.query(EmailMessage)
                    .filter(EmailMessage.mail_account_id == account.id)
                    .filter(EmailMessage.folder == settings.netease_folder)
                    .filter(EmailMessage.imap_uid == uid)
                    .first()
                )
                max_uid = max(max_uid, uid)
                if existing:
                    continue
                status, msg_data = client.uid("fetch", str(uid), "(BODY.PEEK[] FLAGS)")
                if status != "OK" or not msg_data:
                    continue
                raw = _extract_raw_message(msg_data)
                if not raw:
                    continue
                fetched += 1
                email_obj = ingest_raw_email(db, account, uid, raw)
                process_email(db, email_obj.id)
                processed += 1
        state.last_seen_uid = max_uid
        state.sync_status = "idle"
        account.last_sync_at = utcnow()
        db.commit()
        write_internal_calendar(db, account.user_id)
        return {"fetched": fetched, "processed": processed, "message": f"sync completed from {selected_folder}"}
    except Exception as exc:
        state.sync_status = "error"
        state.error_message = str(exc)
        db.commit()
        raise


def _extract_raw_message(msg_data) -> bytes | None:
    for item in msg_data:
        if isinstance(item, tuple) and item[1]:
            return item[1]
    return None


def _send_imap_id(client: imaplib.IMAP4_SSL, email_address: str) -> None:
    # NetEase may reject script clients as "Unsafe Login" unless they identify
    # themselves with the IMAP ID extension before SELECT.
    imaplib.Commands.setdefault("ID", ("AUTH", "SELECTED"))
    args = {
        "name": "Foxmail",
        "version": "7.2.25",
        "vendor": "Tencent",
        "contact": email_address.replace('"', ""),
    }
    payload = "(" + " ".join(f'"{key}" "{value}"' for key, value in args.items()) + ")"
    try:
        client._simple_command("ID", payload)
    except Exception:
        # Some IMAP servers do not support ID. Treat it as best-effort.
        return


def _select_mailbox(client: imaplib.IMAP4_SSL, folder: str) -> str:
    list_status, list_data = client.list()
    listed_mailboxes = _mailbox_names_from_list(list_data if list_status == "OK" else [])
    candidates = [folder, "INBOX", '"INBOX"', "Inbox", "inbox", "&dcVr0mWHTvZZOQ-", *listed_mailboxes]
    seen: set[str] = set()
    failures: list[str] = []
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        status, data = client.select(candidate)
        if status == "OK":
            return candidate
        failures.append(f"{candidate}: {_decode_imap_data(data)}")
        if not (candidate.startswith('"') and candidate.endswith('"')):
            quoted = f'"{candidate}"'
            if quoted not in seen:
                seen.add(quoted)
                status, data = client.select(quoted)
                if status == "OK":
                    return quoted
                failures.append(f"{quoted}: {_decode_imap_data(data)}")
    raw_mailboxes = [item.decode("utf-8", errors="ignore") for item in list_data or [] if item] if list_status == "OK" else []
    failure_text = "; ".join(failures[:6])
    if "Unsafe Login" in failure_text:
        raise RuntimeError("网易邮箱拒绝 IMAP 访问：Unsafe Login。请在网易邮箱安全设置中确认已开启 IMAP/SMTP、使用客户端授权码，并按网易提示完成安全验证后重试。")
    raise RuntimeError(f"无法选择邮箱文件夹 {folder!r}，尝试结果：{failure_text}，可用文件夹：{raw_mailboxes[:10]}")


def _mailbox_names_from_list(items) -> list[str]:
    names: list[str] = []
    for item in items or []:
        line = item.decode("utf-8", errors="ignore") if isinstance(item, bytes) else str(item)
        quoted = re.findall(r'"([^"]+)"', line)
        if quoted:
            names.append(quoted[-1])
            continue
        parts = line.split()
        if parts:
            names.append(parts[-1])
    return names


def _decode_imap_data(data) -> str:
    if not data:
        return ""
    parts: list[str] = []
    for item in data:
        if isinstance(item, bytes):
            parts.append(item.decode("utf-8", errors="ignore"))
        else:
            parts.append(str(item))
    return " ".join(parts)


def ingest_raw_email(db: Session, account: MailAccount, uid: int, raw: bytes) -> EmailMessage:
    parsed = parse_message(raw)
    subject = header_text(parsed, "Subject")
    from_name, from_email = parse_sender(header_text(parsed, "From"))
    to_emails = parse_address_list(header_text(parsed, "To"))
    cc_emails = parse_address_list(header_text(parsed, "Cc"))
    sent_at = parse_datetime(header_text(parsed, "Date"))
    clean_text, html, has_attachments = extract_body(parsed)
    body_hash = sha256_bytes(raw)
    retention_until = utcnow() + timedelta(days=settings.raw_retention_days)

    email_obj = EmailMessage(
        user_id=account.user_id,
        mail_account_id=account.id,
        folder=settings.netease_folder,
        message_id_header=header_text(parsed, "Message-ID")[:512] or None,
        thread_id=header_text(parsed, "In-Reply-To")[:512] or header_text(parsed, "Message-ID")[:512] or None,
        imap_uid=uid,
        subject=subject,
        from_name=from_name,
        from_email=from_email,
        to_emails=dumps(to_emails),
        cc_emails=dumps(cc_emails),
        sent_at=sent_at,
        received_at=utcnow(),
        snippet=snippet(clean_text),
        body_hash=body_hash,
        raw_retention_until=retention_until,
        has_attachments=has_attachments,
    )
    db.add(email_obj)
    db.commit()
    db.refresh(email_obj)

    email_obj.raw_mime_ref = write_email_blob(email_obj.id, "raw.eml", raw)
    email_obj.text_ref = write_email_blob(email_obj.id, "body.txt", clean_text)
    if html:
        email_obj.html_ref = write_email_blob(email_obj.id, "body.html", html)
    db.commit()
    return email_obj


def process_email(db: Session, email_id: int) -> None:
    email_obj = db.get(EmailMessage, email_id)
    if not email_obj:
        return
    clean_text = _read_clean_text(email_obj)
    links = extract_links(clean_text)
    parsed = db.query(EmailParsedContent).filter(EmailParsedContent.email_id == email_id).first()
    if not parsed:
        parsed = EmailParsedContent(email_id=email_id)
        db.add(parsed)
    parsed.clean_text = clean_text
    parsed.links_json = dumps(links)
    parsed.parse_status = "parsed"
    db.commit()

    classification = classify_email(email_obj.subject, email_obj.from_email, clean_text)
    cls = db.query(EmailClassification).filter(EmailClassification.email_id == email_id).first()
    if not cls:
        cls = EmailClassification(email_id=email_id)
        db.add(cls)
    cls.category = classification.category
    cls.confidence = classification.confidence
    cls.reason = classification.reason
    cls.evidence_json = dumps(classification.evidence)
    cls.model_name = classification.model_name
    db.commit()

    _upsert_event_from_email(db, email_obj, cls.category, clean_text)
    _upsert_task_from_email(db, email_obj, cls.category, clean_text)
    write_internal_calendar(db, email_obj.user_id)


def _read_clean_text(email_obj: EmailMessage) -> str:
    from app.services.storage import read_text_ref

    return read_text_ref(email_obj.text_ref)


def _upsert_event_from_email(db: Session, email_obj: EmailMessage, category: str, clean_text: str) -> None:
    candidate = extract_event(email_obj.subject, category, clean_text, email_obj.sent_at)
    if not candidate:
        return
    dedupe_key = f"{email_obj.user_id}:{candidate.event_type}:{candidate.company or ''}:{candidate.start_time or ''}:{candidate.meeting_link or ''}"
    existing = db.query(ExtractedEvent).filter(ExtractedEvent.dedupe_key == dedupe_key).first()
    event = existing or ExtractedEvent(user_id=email_obj.user_id, source_email_id=email_obj.id, event_type=candidate.event_type, title=candidate.title)
    event.source_email_id = email_obj.id
    event.event_type = candidate.event_type
    event.title = candidate.title
    event.company = candidate.company
    event.description = "\n".join(candidate.evidence)
    event.start_time = candidate.start_time
    event.end_time = candidate.end_time
    event.timezone = candidate.timezone
    event.location = candidate.location
    event.meeting_link = candidate.meeting_link
    event.confidence = candidate.confidence
    event.status = "needs_review" if candidate.missing_fields else "draft"
    event.missing_fields_json = dumps(candidate.missing_fields)
    event.evidence_json = dumps(candidate.evidence)
    event.dedupe_key = dedupe_key
    if not existing:
        db.add(event)
    db.commit()
    db.refresh(event)
    _ensure_event_reminder(db, email_obj.user_id, event)
    _ensure_review_reminder(db, email_obj.user_id, event)
    detect_conflicts_for_event(db, event)


def _ensure_event_reminder(db: Session, user_id: int, event: ExtractedEvent) -> None:
    if not event.start_time:
        return
    remind_at = event.start_time - timedelta(days=settings.reminder_days_before)
    existing = (
        db.query(Reminder)
        .filter(Reminder.target_type == "event")
        .filter(Reminder.target_id == event.id)
        .first()
    )
    if existing:
        existing.remind_at = remind_at
        existing.payload_json = dumps({"title": event.title})
    else:
        db.add(
            Reminder(
                user_id=user_id,
                target_type="event",
                target_id=event.id,
                remind_at=remind_at,
                payload_json=dumps({"title": event.title}),
            )
        )
    db.commit()


def _ensure_review_reminder(db: Session, user_id: int, event: ExtractedEvent) -> None:
    if event.status != "needs_review":
        return
    existing = (
        db.query(Reminder)
        .filter(Reminder.target_type == "review")
        .filter(Reminder.target_id == event.id)
        .first()
    )
    if existing:
        return
    db.add(
        Reminder(
            user_id=user_id,
            target_type="review",
            target_id=event.id,
            remind_at=utcnow(),
            payload_json=dumps({"title": event.title, "reason": "event_needs_review"}),
        )
    )
    db.commit()


def _upsert_task_from_email(db: Session, email_obj: EmailMessage, category: str, clean_text: str) -> None:
    candidate = extract_task(email_obj.subject, category, clean_text, email_obj.sent_at)
    if not candidate:
        return
    existing = db.query(Task).filter(Task.source_email_id == email_obj.id).first()
    task = existing or Task(user_id=email_obj.user_id, source_email_id=email_obj.id, title=candidate.title)
    task.title = candidate.title
    task.description = candidate.description
    task.due_at = candidate.due_at
    task.priority = candidate.priority
    task.confidence = candidate.confidence
    task.evidence_json = dumps(candidate.evidence)
    if not existing:
        db.add(task)
    db.commit()
    db.refresh(task)
    _ensure_task_reminder(db, email_obj.user_id, task)


def _ensure_task_reminder(db: Session, user_id: int, task: Task) -> None:
    if not task.due_at:
        return
    remind_at = task.due_at - timedelta(days=settings.reminder_days_before)
    existing = (
        db.query(Reminder)
        .filter(Reminder.target_type == "task")
        .filter(Reminder.target_id == task.id)
        .first()
    )
    if existing:
        existing.remind_at = remind_at
        existing.payload_json = dumps({"title": task.title})
    else:
        db.add(
            Reminder(
                user_id=user_id,
                target_type="task",
                target_id=task.id,
                remind_at=remind_at,
                payload_json=dumps({"title": task.title}),
            )
        )
    db.commit()


def reprocess_all(db: Session) -> int:
    emails = db.query(EmailMessage).all()
    for email_obj in emails:
        process_email(db, email_obj.id)
    return len(emails)
