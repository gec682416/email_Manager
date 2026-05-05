from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    EmailClassification,
    EmailMessage,
    EventConflict,
    ExtractedEvent,
    MailAccount,
    Task,
    UserMemory,
)
from app.services.calendar_ics import write_internal_calendar
from app.services.conflicts import open_conflicts_for_user
from app.services.json_utils import loads_list
from app.services.storage import read_text_ref


@dataclass
class ToolResult:
    tool_name: str
    arguments: dict[str, Any]
    preview: str
    data: Any
    source_refs: list[dict[str, Any]]


def run_agent_tool(db: Session, user_id: int, tool_name: str, arguments: dict[str, Any], user_question: str) -> ToolResult:
    args = arguments if isinstance(arguments, dict) else {}
    if tool_name == "time.now":
        return _time_now(tool_name, args)
    if tool_name == "mail.search":
        return _mail_search(db, user_id, tool_name, args)
    if tool_name == "mail.get_detail":
        return _mail_get_detail(db, user_id, tool_name, args)
    if tool_name == "event.query":
        return _event_query(db, user_id, tool_name, args)
    if tool_name == "task.query":
        return _task_query(db, user_id, tool_name, args)
    if tool_name == "calendar.file_info":
        return _calendar_file_info(db, user_id, tool_name, args)
    if tool_name == "conflict.query":
        return _conflict_query(db, user_id, tool_name, args)
    if tool_name == "memory.read":
        return _memory_read(db, user_id, tool_name, args)
    if tool_name == "memory.write_preference":
        return _memory_write_preference(db, user_id, tool_name, args, user_question)
    return ToolResult(tool_name, args, f"未知工具：{tool_name}", {"error": "unknown_tool"}, [])


def compact_tool_result(result: ToolResult, max_items: int = 8) -> dict[str, Any]:
    data = result.data
    if isinstance(data, list):
        data = data[:max_items]
    return {
        "tool_name": result.tool_name,
        "arguments": result.arguments,
        "preview": result.preview,
        "data": data,
        "source_refs": result.source_refs,
    }


def available_tools_spec() -> list[dict[str, Any]]:
    return [
        {
            "name": "time.now",
            "description": "读取当前时间、时区和日期，处理今天/明天/本周等相对时间前应优先调用。",
            "arguments": {},
        },
        {
            "name": "mail.search",
            "description": "查询已同步邮件。支持关键词、分类、最近天数和数量限制。返回邮件摘要，不返回完整正文。",
            "arguments": {
                "keyword": "可选，按主题/发件人/摘要/正文片段搜索",
                "category": "可选，如 interview/written_test/meeting_invite/deadline/todo_request/notification",
                "days": "可选，最近多少天",
                "limit": "可选，默认 10，最大 30",
            },
        },
        {
            "name": "mail.get_detail",
            "description": "读取单封邮件的正文详情。只有需要引用证据或细节时调用。",
            "arguments": {"email_id": "邮件 ID"},
        },
        {
            "name": "event.query",
            "description": "查询内部日历事件。适合面试、笔试、会议、日程冲突、未来安排等问题。",
            "arguments": {
                "keyword": "可选，按标题/公司/描述搜索",
                "event_type": "可选，如 interview/written_test/meeting/deadline",
                "status": "可选，如 draft/needs_review/confirmed/ignored",
                "start": "可选，ISO 日期时间",
                "end": "可选，ISO 日期时间",
                "days_ahead": "可选，从今天起向后查询多少天",
                "limit": "可选，默认 20，最大 50",
            },
        },
        {
            "name": "task.query",
            "description": "查询待办任务和截止事项。",
            "arguments": {"status": "可选，默认 open", "limit": "可选，默认 20"},
        },
        {
            "name": "calendar.file_info",
            "description": "查看内部 ICS 日历文件路径、是否存在、已写入的有效事件数量。",
            "arguments": {},
        },
        {
            "name": "conflict.query",
            "description": "查询当前打开的日程冲突和需要人工确认的时间问题。",
            "arguments": {"limit": "可选，默认 20"},
        },
        {
            "name": "memory.read",
            "description": "读取和当前问题相关的长期记忆。",
            "arguments": {"keyword": "可选，按关键词搜索 memory"},
        },
        {
            "name": "memory.write_preference",
            "description": "仅当用户明确说“记住/以后/我的偏好”时写入长期偏好记忆。",
            "arguments": {"title": "偏好标题", "content": "偏好内容", "memory_type": "默认 user_preference"},
        },
    ]


def collect_heuristic_context(db: Session, user_id: int, question: str) -> list[ToolResult]:
    results = [_time_now("time.now", {})]
    lower = question.lower()
    if any(k in question for k in ["面试", "笔试", "会议", "日程", "安排", "冲突", "calendar", "event"]):
        results.append(_event_query(db, user_id, "event.query", _window_args(question)))
    if any(k in question for k in ["冲突", "重叠", "撞", "conflict"]):
        results.append(_conflict_query(db, user_id, "conflict.query", {"limit": 20}))
    if any(k in question for k in ["待办", "任务", "截止", "todo", "deadline", "ddl"]):
        results.append(_task_query(db, user_id, "task.query", {"status": "open", "limit": 20}))
    if any(k in question for k in ["邮件", "邮箱", "offer", "拒", "hr", "简历", "笔试", "面试", "mail", "email"]) or len(results) == 1:
        category = None
        if "面试" in question or "interview" in lower:
            category = "interview"
        elif "笔试" in question or "测评" in question or "assessment" in lower:
            category = "written_test"
        elif "offer" in lower or "录用" in question:
            category = "offer"
        results.append(_mail_search(db, user_id, "mail.search", {"category": category, "keyword": None, "limit": 10}))
    return results


def _time_now(tool_name: str, args: dict[str, Any]) -> ToolResult:
    tz = ZoneInfo(settings.default_timezone)
    now = datetime.now(tz)
    data = {
        "now": now.isoformat(),
        "date": now.date().isoformat(),
        "timezone": settings.default_timezone,
        "weekday": now.strftime("%A"),
    }
    return ToolResult(tool_name, args, f"当前时间：{now.strftime('%Y-%m-%d %H:%M:%S')} {settings.default_timezone}", data, [])


def _mail_search(db: Session, user_id: int, tool_name: str, args: dict[str, Any]) -> ToolResult:
    limit = _bounded_int(args.get("limit"), default=10, low=1, high=30)
    query = db.query(EmailMessage).filter(EmailMessage.user_id == user_id).filter(EmailMessage.local_deleted_at.is_(None))

    category = _clean_str(args.get("category"))
    if category:
        query = query.join(EmailClassification, EmailClassification.email_id == EmailMessage.id).filter(EmailClassification.category == category)

    days = _optional_int(args.get("days"))
    if days:
        since = datetime.now(ZoneInfo(settings.default_timezone)) - timedelta(days=max(days, 1))
        query = query.filter(EmailMessage.received_at >= since)

    keyword = _clean_str(args.get("keyword"))
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            or_(
                EmailMessage.subject.ilike(like),
                EmailMessage.from_email.ilike(like),
                EmailMessage.snippet.ilike(like),
            )
        )

    emails = query.order_by(EmailMessage.received_at.desc()).limit(limit).all()
    data = [_email_summary(email) for email in emails]
    refs = [{"type": "email", "id": email.id} for email in emails]
    return ToolResult(tool_name, args, f"找到 {len(data)} 封邮件", data, refs)


def _mail_get_detail(db: Session, user_id: int, tool_name: str, args: dict[str, Any]) -> ToolResult:
    email_id = _optional_int(args.get("email_id"))
    if not email_id:
        return ToolResult(tool_name, args, "缺少 email_id", {"error": "missing_email_id"}, [])
    email = db.get(EmailMessage, email_id)
    if not email or email.user_id != user_id or email.local_deleted_at is not None:
        return ToolResult(tool_name, args, "没有找到这封邮件", {"error": "email_not_found"}, [])
    clean_text = email.parsed.clean_text if email.parsed else read_text_ref(email.text_ref)
    data = _email_summary(email)
    data["clean_text"] = clean_text[:4000]
    data["links"] = loads_list(email.parsed.links_json if email.parsed else None)
    return ToolResult(tool_name, args, f"读取邮件 {email.id}：{email.subject[:80]}", data, [{"type": "email", "id": email.id}])


def _event_query(db: Session, user_id: int, tool_name: str, args: dict[str, Any]) -> ToolResult:
    limit = _bounded_int(args.get("limit"), default=20, low=1, high=50)
    query = db.query(ExtractedEvent).filter(ExtractedEvent.user_id == user_id)

    status = _clean_str(args.get("status"))
    if status:
        query = query.filter(ExtractedEvent.status == status)

    event_type = _clean_str(args.get("event_type"))
    if event_type:
        query = query.filter(ExtractedEvent.event_type == event_type)

    start = _parse_dt(args.get("start"))
    end = _parse_dt(args.get("end"))
    days_ahead = _optional_int(args.get("days_ahead"))
    if days_ahead and not start and not end:
        tz = ZoneInfo(settings.default_timezone)
        start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=max(days_ahead, 1))

    if start:
        query = query.filter(ExtractedEvent.start_time >= start)
    if end:
        query = query.filter(ExtractedEvent.start_time < end)

    keyword = _clean_str(args.get("keyword"))
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            or_(
                ExtractedEvent.title.ilike(like),
                ExtractedEvent.company.ilike(like),
                ExtractedEvent.description.ilike(like),
            )
        )

    events = query.order_by(ExtractedEvent.start_time.asc().nullslast(), ExtractedEvent.created_at.desc()).limit(limit).all()
    data = [_event_summary(event) for event in events]
    refs = [{"type": "event", "id": event.id, "source_email_id": event.source_email_id} for event in events]
    return ToolResult(tool_name, args, f"找到 {len(data)} 个日程", data, refs)


def _task_query(db: Session, user_id: int, tool_name: str, args: dict[str, Any]) -> ToolResult:
    limit = _bounded_int(args.get("limit"), default=20, low=1, high=50)
    query = db.query(Task).filter(Task.user_id == user_id)
    status = _clean_str(args.get("status")) or "open"
    query = query.filter(Task.status == status)
    tasks = query.order_by(Task.due_at.asc().nullslast(), Task.created_at.desc()).limit(limit).all()
    data = [_task_summary(task) for task in tasks]
    refs = [{"type": "task", "id": task.id, "source_email_id": task.source_email_id} for task in tasks]
    return ToolResult(tool_name, args, f"找到 {len(data)} 个待办", data, refs)


def _calendar_file_info(db: Session, user_id: int, tool_name: str, args: dict[str, Any]) -> ToolResult:
    path = Path(write_internal_calendar(db, user_id))
    count = db.query(ExtractedEvent).filter(ExtractedEvent.user_id == user_id).filter(ExtractedEvent.status != "ignored").count()
    data = {
        "path": str(path),
        "exists": path.exists(),
        "event_count": count,
        "download_url": "/api/calendar.ics",
    }
    return ToolResult(tool_name, args, f"ICS 日历文件已生成，包含 {count} 个有效日程", data, [])


def _conflict_query(db: Session, user_id: int, tool_name: str, args: dict[str, Any]) -> ToolResult:
    limit = _bounded_int(args.get("limit"), default=20, low=1, high=50)
    conflicts = open_conflicts_for_user(db, user_id)[:limit]
    data = [_conflict_summary(db, conflict) for conflict in conflicts]
    refs = [{"type": "conflict", "id": conflict.id, "event_id": conflict.event_id} for conflict in conflicts]
    return ToolResult(tool_name, args, f"找到 {len(data)} 个打开的冲突", data, refs)


def _memory_read(db: Session, user_id: int, tool_name: str, args: dict[str, Any]) -> ToolResult:
    query = db.query(UserMemory).filter(UserMemory.user_id == user_id).filter(UserMemory.status == "active")
    keyword = _clean_str(args.get("keyword"))
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(or_(UserMemory.title.ilike(like), UserMemory.content.ilike(like), UserMemory.memory_type.ilike(like)))
    memories = query.order_by(UserMemory.updated_at.desc()).limit(10).all()
    data = [
        {
            "id": memory.id,
            "memory_type": memory.memory_type,
            "title": memory.title,
            "content": memory.content,
            "confidence": memory.confidence,
            "updated_at": _iso(memory.updated_at),
        }
        for memory in memories
    ]
    refs = [{"type": "memory", "id": memory.id} for memory in memories]
    return ToolResult(tool_name, args, f"找到 {len(data)} 条长期记忆", data, refs)


def _memory_write_preference(db: Session, user_id: int, tool_name: str, args: dict[str, Any], user_question: str) -> ToolResult:
    if not any(k in user_question for k in ["记住", "以后", "偏好", "我的习惯", "默认"]):
        return ToolResult(tool_name, args, "用户没有明确要求写入长期记忆，已拒绝写入", {"skipped": True, "reason": "no_explicit_memory_intent"}, [])
    title = _clean_str(args.get("title")) or "用户偏好"
    content = _clean_str(args.get("content")) or user_question
    memory_type = _clean_str(args.get("memory_type")) or "user_preference"
    memory = UserMemory(user_id=user_id, memory_type=memory_type, title=title[:255], content=content, confidence=0.9)
    db.add(memory)
    db.commit()
    db.refresh(memory)
    data = {"id": memory.id, "memory_type": memory.memory_type, "title": memory.title, "content": memory.content}
    return ToolResult(tool_name, args, f"已写入长期记忆：{memory.title}", data, [{"type": "memory", "id": memory.id}])


def _email_summary(email: EmailMessage) -> dict[str, Any]:
    classification = email.classification
    return {
        "id": email.id,
        "subject": email.subject,
        "from_name": email.from_name,
        "from_email": email.from_email,
        "sent_at": _iso(email.sent_at),
        "received_at": _iso(email.received_at),
        "snippet": email.snippet,
        "category": classification.category if classification else None,
        "confidence": classification.confidence if classification else None,
    }


def _event_summary(event: ExtractedEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "source_email_id": event.source_email_id,
        "event_type": event.event_type,
        "title": event.title,
        "company": event.company,
        "start_time": _iso(event.start_time),
        "end_time": _iso(event.end_time),
        "timezone": event.timezone,
        "location": event.location,
        "meeting_link": event.meeting_link,
        "status": event.status,
        "confidence": event.confidence,
        "description": event.description[:500],
        "evidence": loads_list(event.evidence_json),
    }


def _task_summary(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "source_email_id": task.source_email_id,
        "title": task.title,
        "description": task.description[:500],
        "due_at": _iso(task.due_at),
        "priority": task.priority,
        "status": task.status,
        "confidence": task.confidence,
        "evidence": loads_list(task.evidence_json),
    }


def _conflict_summary(db: Session, conflict: EventConflict) -> dict[str, Any]:
    event = db.get(ExtractedEvent, conflict.event_id)
    other = db.get(ExtractedEvent, conflict.conflict_event_id) if conflict.conflict_event_id else None
    return {
        "id": conflict.id,
        "event_id": conflict.event_id,
        "event_title": event.title if event else None,
        "event_start_time": _iso(event.start_time) if event else None,
        "conflict_event_id": conflict.conflict_event_id,
        "conflict_event_title": other.title if other else None,
        "conflict_event_start_time": _iso(other.start_time) if other else None,
        "conflict_type": conflict.conflict_type,
        "severity": conflict.severity,
        "description": conflict.description,
        "status": conflict.status,
    }


def _window_args(question: str) -> dict[str, Any]:
    tz = ZoneInfo(settings.default_timezone)
    now = datetime.now(tz)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if "今天" in question:
        return {"start": today.isoformat(), "end": (today + timedelta(days=1)).isoformat(), "limit": 20}
    if "明天" in question:
        start = today + timedelta(days=1)
        return {"start": start.isoformat(), "end": (start + timedelta(days=1)).isoformat(), "limit": 20}
    if "这周" in question or "本周" in question:
        start = today - timedelta(days=today.weekday())
        return {"start": start.isoformat(), "end": (start + timedelta(days=7)).isoformat(), "limit": 30}
    if "下周" in question:
        start = today - timedelta(days=today.weekday()) + timedelta(days=7)
        return {"start": start.isoformat(), "end": (start + timedelta(days=7)).isoformat(), "limit": 30}
    return {"days_ahead": 30, "limit": 20}


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(settings.default_timezone))
    return parsed


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _bounded_int(value: Any, *, default: int, low: int, high: int) -> int:
    parsed = _optional_int(value)
    if parsed is None:
        return default
    return min(max(parsed, low), high)


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
