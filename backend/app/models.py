from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), default="Local User")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Singapore")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class MailAccount(Base):
    __tablename__ = "mail_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(64), default="netease")
    email_address: Mapped[str] = mapped_column(String(255), index=True)
    imap_host: Mapped[str] = mapped_column(String(255), default="imap.163.com")
    imap_port: Mapped[int] = mapped_column(Integer, default=993)
    imap_secure: Mapped[bool] = mapped_column(Boolean, default=True)
    encrypted_app_password: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(64), default="active")
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class MailboxSyncState(Base):
    __tablename__ = "mailbox_sync_states"
    __table_args__ = (UniqueConstraint("mail_account_id", "folder", name="uq_sync_account_folder"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mail_account_id: Mapped[int] = mapped_column(ForeignKey("mail_accounts.id"), index=True)
    folder: Mapped[str] = mapped_column(String(255), default="INBOX")
    uid_validity: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_seen_uid: Mapped[int] = mapped_column(Integer, default=0)
    sync_status: Mapped[str] = mapped_column(String(64), default="idle")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class EmailMessage(Base):
    __tablename__ = "email_messages"
    __table_args__ = (UniqueConstraint("mail_account_id", "folder", "imap_uid", name="uq_email_uid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    mail_account_id: Mapped[int] = mapped_column(ForeignKey("mail_accounts.id"), index=True)
    folder: Mapped[str] = mapped_column(String(255), default="INBOX")
    message_id_header: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    thread_id: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    imap_uid: Mapped[int] = mapped_column(Integer, index=True)
    subject: Mapped[str] = mapped_column(Text, default="")
    from_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    from_email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    to_emails: Mapped[str] = mapped_column(Text, default="[]")
    cc_emails: Mapped[str] = mapped_column(Text, default="[]")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    snippet: Mapped[str] = mapped_column(Text, default="")
    raw_mime_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    html_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    local_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    has_attachments: Mapped[bool] = mapped_column(Boolean, default=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    sync_status: Mapped[str] = mapped_column(String(64), default="synced")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    parsed: Mapped["EmailParsedContent"] = relationship(back_populates="email", uselist=False)
    classification: Mapped["EmailClassification"] = relationship(back_populates="email", uselist=False)


class EmailParsedContent(Base):
    __tablename__ = "email_parsed_contents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email_id: Mapped[int] = mapped_column(ForeignKey("email_messages.id"), unique=True, index=True)
    clean_text: Mapped[str] = mapped_column(Text, default="")
    links_json: Mapped[str] = mapped_column(Text, default="[]")
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    parse_status: Mapped[str] = mapped_column(String(64), default="parsed")
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    email: Mapped[EmailMessage] = relationship(back_populates="parsed")


class EmailClassification(Base):
    __tablename__ = "email_classifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email_id: Mapped[int] = mapped_column(ForeignKey("email_messages.id"), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[str] = mapped_column(Text, default="")
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    model_name: Mapped[str] = mapped_column(String(128), default="rules")
    prompt_version: Mapped[str] = mapped_column(String(64), default="email_classify_v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    email: Mapped[EmailMessage] = relationship(back_populates="classification")


class ExtractedEvent(Base):
    __tablename__ = "extracted_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    source_email_id: Mapped[int | None] = mapped_column(ForeignKey("email_messages.id"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(Text)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Singapore")
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    meeting_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(64), default="draft", index=True)
    missing_fields_json: Mapped[str] = mapped_column(Text, default="[]")
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    dedupe_key: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class EventConflict(Base):
    __tablename__ = "event_conflicts"
    __table_args__ = (UniqueConstraint("event_id", "conflict_event_id", "conflict_type", name="uq_event_conflict_pair"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("extracted_events.id"), index=True)
    conflict_event_id: Mapped[int | None] = mapped_column(ForeignKey("extracted_events.id"), nullable=True, index=True)
    conflict_type: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(32), default="warning")
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(64), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    source_email_id: Mapped[int | None] = mapped_column(ForeignKey("email_messages.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    priority: Mapped[str] = mapped_column(String(32), default="medium")
    status: Mapped[str] = mapped_column(String(64), default="open", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    target_type: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[int] = mapped_column(Integer, index=True)
    remind_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    channel: Mapped[str] = mapped_column(String(64), default="in_app")
    status: Mapped[str] = mapped_column(String(64), default="pending", index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserMemory(Base):
    __tablename__ = "user_memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    memory_type: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    status: Mapped[str] = mapped_column(String(64), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    run_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(64), default="completed")
    input_text: Mapped[str] = mapped_column(Text, default="")
    output_text: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    model_name: Mapped[str] = mapped_column(String(128), default="")
    jsonl_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
