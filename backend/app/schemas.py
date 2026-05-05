from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str
    timezone: str


class MailAccountCreate(BaseModel):
    email_address: EmailStr
    app_password: str = Field(min_length=1)
    imap_host: str = "imap.163.com"
    imap_port: int = 993


class MailAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    email_address: str
    imap_host: str
    imap_port: int
    status: str
    last_sync_at: datetime | None


class SyncResult(BaseModel):
    account_id: int
    fetched: int
    processed: int
    message: str


class EmailOut(BaseModel):
    id: int
    subject: str
    from_name: str | None
    from_email: str | None
    sent_at: datetime | None
    received_at: datetime | None
    snippet: str
    category: str | None = None
    confidence: float | None = None


class EmailDetail(EmailOut):
    clean_text: str = ""
    links: list[str] = []
    evidence: list[str] = []


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_email_id: int | None
    event_type: str
    title: str
    company: str | None
    description: str
    start_time: datetime | None
    end_time: datetime | None
    timezone: str
    location: str | None
    meeting_link: str | None
    confidence: float
    status: str
    missing_fields: list[str] = []
    evidence: list[str] = []
    conflicts: list[dict[str, Any]] = []


class EventUpdate(BaseModel):
    title: str | None = None
    company: str | None = None
    description: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    timezone: str | None = None
    location: str | None = None
    meeting_link: str | None = None
    status: str | None = None


class EventConflictOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_id: int
    conflict_event_id: int | None
    conflict_type: str
    severity: str
    description: str
    status: str


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_email_id: int | None
    title: str
    description: str
    due_at: datetime | None
    priority: str
    status: str
    confidence: float


class ReminderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    target_type: str
    target_id: int
    remind_at: datetime
    channel: str
    status: str


class AgentQuery(BaseModel):
    question: str


class AgentAnswer(BaseModel):
    answer: str
    source_refs: list[dict[str, Any]] = []
    last_sync_at: datetime | None = None
    run_id: int | None = None
    model_name: str | None = None
    tool_trace: list[dict[str, Any]] = []


class AgentRunOut(BaseModel):
    id: int
    run_type: str
    status: str
    input_text: str
    output_text: str
    summary: str
    model_name: str
    jsonl_ref: str | None = None
    events: list[dict[str, Any]] = []
    created_at: datetime


class DashboardOut(BaseModel):
    last_sync_at: datetime | None
    email_count: int
    event_count: int
    task_count: int
    conflict_count: int = 0
    pending_review_count: int
    upcoming_events: list[EventOut]
    reminders: list[ReminderOut]
