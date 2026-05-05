from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import EmailMessage, utcnow
from app.services.storage import remove_email_blob_dir, remove_ref


def delete_local_email_copy(db: Session, email: EmailMessage) -> dict[str, int | bool]:
    deleted_files = 0
    for ref in [email.raw_mime_ref, email.html_ref, email.text_ref]:
        if remove_ref(ref):
            deleted_files += 1
    if remove_email_blob_dir(email.id):
        deleted_files += 1

    email.raw_mime_ref = None
    email.html_ref = None
    email.text_ref = None
    email.local_deleted_at = utcnow()
    db.commit()
    return {"email_id": email.id, "deleted_files": deleted_files, "server_mail_deleted": False}


def cleanup_expired_raw_copies(db: Session) -> dict[str, int | bool]:
    now = datetime.now(timezone.utc)
    emails = (
        db.query(EmailMessage)
        .filter(EmailMessage.local_deleted_at.is_(None))
        .filter(EmailMessage.raw_retention_until.isnot(None))
        .filter(EmailMessage.raw_retention_until <= now)
        .all()
    )
    deleted_files = 0
    for email in emails:
        result = delete_local_email_copy(db, email)
        deleted_files += int(result["deleted_files"])
    return {"emails_cleaned": len(emails), "deleted_files": deleted_files, "server_mail_deleted": False}
