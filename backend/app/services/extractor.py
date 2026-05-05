from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import dateparser

from app.config import settings
from app.services.qwen import qwen_client


MEETING_LINK_RE = re.compile(r"https?://[^\s<>'\")]+", re.IGNORECASE)
COMPANY_RE = re.compile(r"([\u4e00-\u9fa5A-Za-z0-9]+(?:公司|集团|科技|网络|University|Inc\.?|Ltd\.?))")


@dataclass
class EventCandidate:
    event_type: str
    title: str
    start_time: datetime | None
    end_time: datetime | None
    timezone: str
    location: str | None
    meeting_link: str | None
    company: str | None
    confidence: float
    missing_fields: list[str]
    evidence: list[str]


@dataclass
class TaskCandidate:
    title: str
    description: str
    due_at: datetime | None
    priority: str
    confidence: float
    evidence: list[str]


def extract_event(subject: str, category: str, clean_text: str, sent_at: datetime | None) -> EventCandidate | None:
    if category not in {"interview", "written_test", "meeting_invite", "deadline", "calendar_update"}:
        return None
    body = clean_text[:6000]
    tz_name = settings.default_timezone
    start = parse_best_datetime(body, sent_at)
    qwen_candidate = _extract_event_with_qwen(subject, category, body, sent_at)
    if qwen_candidate and (not start or qwen_candidate.confidence >= 0.75):
        return qwen_candidate
    duration = timedelta(hours=2 if category == "written_test" else 1)
    end = start + duration if start else None
    links = MEETING_LINK_RE.findall(body)
    company = extract_company(subject, body)
    event_type = "meeting" if category == "meeting_invite" else category
    missing = []
    if start is None:
        missing.append("start_time")
    title_parts = []
    if company:
        title_parts.append(company)
    title_parts.append(_event_type_label(event_type))
    title = " - ".join(title_parts) if title_parts else subject or _event_type_label(event_type)
    evidence = _evidence_lines(body)
    return EventCandidate(
        event_type=event_type,
        title=title,
        start_time=start,
        end_time=end,
        timezone=tz_name,
        location=_extract_location(body),
        meeting_link=links[0].rstrip("。.,，)") if links else None,
        company=company,
        confidence=0.84 if start else 0.52,
        missing_fields=missing,
        evidence=evidence,
    )


def extract_task(subject: str, category: str, clean_text: str, sent_at: datetime | None) -> TaskCandidate | None:
    if category not in {"todo_request", "hr_followup", "deadline"}:
        return None
    qwen_candidate = _extract_task_with_qwen(subject, category, clean_text[:5000], sent_at)
    if qwen_candidate:
        return qwen_candidate
    due_at = parse_best_datetime(clean_text, sent_at)
    evidence = _evidence_lines(clean_text)
    return TaskCandidate(
        title=subject or "邮件待办",
        description="\n".join(evidence) or clean_text[:300],
        due_at=due_at,
        priority="high" if category == "deadline" else "medium",
        confidence=0.72,
        evidence=evidence,
    )


def parse_best_datetime(text: str, sent_at: datetime | None) -> datetime | None:
    tz = ZoneInfo(settings.default_timezone)
    base = sent_at.astimezone(tz) if sent_at else datetime.now(tz)
    candidates = _time_candidates(text)
    settings_dict = {
        "RELATIVE_BASE": base.replace(tzinfo=None),
        "TIMEZONE": settings.default_timezone,
        "RETURN_AS_TIMEZONE_AWARE": True,
        "PREFER_DATES_FROM": "future",
    }
    for candidate in candidates:
        dt = dateparser.parse(candidate, languages=["zh", "en"], settings=settings_dict)
        if dt:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz)
            return dt
    return None


def _time_candidates(text: str) -> list[str]:
    patterns = [
        r"\d{4}[年/-]\d{1,2}[月/-]\d{1,2}[日号]?\s*(?:上午|下午|晚上)?\s*\d{1,2}[:：点]\d{0,2}",
        r"\d{1,2}月\d{1,2}[日号]\s*(?:上午|下午|晚上)?\s*\d{1,2}[:：点]\d{0,2}",
        r"(?:今天|明天|后天|下周[一二三四五六日天]|周[一二三四五六日天])\s*(?:上午|下午|晚上)?\s*\d{1,2}[:：点]\d{0,2}",
        r"\d{4}-\d{1,2}-\d{1,2}\s+\d{1,2}:\d{2}",
        r"\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}",
    ]
    matches: list[str] = []
    for pattern in patterns:
        matches.extend(m.group(0) for m in re.finditer(pattern, text))
    if not matches:
        lines = [line.strip() for line in text.splitlines() if any(k in line for k in ["时间", "日期", "面试", "笔试", "meeting", "interview"])]
        matches.extend(lines[:5])
    normalized: list[str] = []
    for item in matches:
        value = item.replace("：", ":").replace("点", ":00")
        normalized.append(value)
    return normalized


def extract_company(subject: str, body: str) -> str | None:
    match = COMPANY_RE.search(f"{subject}\n{body[:1000]}")
    return match.group(1) if match else None


def _extract_location(text: str) -> str | None:
    for line in text.splitlines():
        if any(k in line.lower() for k in ["地点", "地址", "腾讯会议", "zoom", "teams", "meeting link"]):
            return line.strip()[:300]
    return None


def _event_type_label(event_type: str) -> str:
    return {
        "interview": "面试",
        "written_test": "笔试",
        "meeting": "会议",
        "deadline": "截止事项",
        "calendar_update": "日程更新",
    }.get(event_type, "日程")


def _evidence_lines(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    useful = []
    keys = ["时间", "日期", "地点", "会议", "面试", "笔试", "链接", "zoom", "腾讯会议", "interview", "assessment"]
    for line in lines:
        if any(k.lower() in line.lower() for k in keys):
            useful.append(line[:300])
    return useful[:5]


def _extract_event_with_qwen(subject: str, category: str, body: str, sent_at: datetime | None) -> EventCandidate | None:
    if not qwen_client.enabled:
        return None
    system = (
        "你是邮件事件抽取器。只输出 JSON，不要 Markdown。"
        "从邮件中抽取面试、笔试、会议、截止事项。缺失字段用 null 或空数组。"
        "时间必须尽量输出 ISO 8601，时区默认 Asia/Singapore。"
    )
    user = f"""
分类: {category}
邮件发送时间: {sent_at.isoformat() if sent_at else ""}
默认时区: {settings.default_timezone}
Subject: {subject}
Body:
{body[:5000]}

输出 JSON schema:
{{
  "has_event": true,
  "event_type": "interview | written_test | meeting | deadline | calendar_update",
  "title": "string",
  "company": "string or null",
  "start_time": "ISO datetime or null",
  "end_time": "ISO datetime or null",
  "location": "string or null",
  "meeting_link": "string or null",
  "confidence": 0.0,
  "missing_fields": ["start_time"],
  "evidence": ["原文证据片段"]
}}
"""
    data = qwen_client.chat_json(model=settings.qwen_classifier_model, system=system, user=user, max_tokens=900)
    if not data or data.get("has_event") is False:
        return None
    start = _parse_qwen_dt(data.get("start_time"))
    end = _parse_qwen_dt(data.get("end_time"))
    event_type = str(data.get("event_type") or ("meeting" if category == "meeting_invite" else category))
    evidence = _list_str(data.get("evidence")) or _evidence_lines(body)
    missing = _list_str(data.get("missing_fields"))
    if not start and "start_time" not in missing:
        missing.append("start_time")
    title = str(data.get("title") or subject or _event_type_label(event_type))
    return EventCandidate(
        event_type=event_type,
        title=title,
        start_time=start,
        end_time=end,
        timezone=settings.default_timezone,
        location=_clean_optional(data.get("location")),
        meeting_link=_clean_optional(data.get("meeting_link")),
        company=_clean_optional(data.get("company")),
        confidence=float(data.get("confidence") or (0.8 if start else 0.55)),
        missing_fields=missing,
        evidence=evidence[:5],
    )


def _extract_task_with_qwen(subject: str, category: str, body: str, sent_at: datetime | None) -> TaskCandidate | None:
    if not qwen_client.enabled:
        return None
    system = "你是邮件待办抽取器。只输出 JSON，不要 Markdown。抽取用户需要执行的任务或截止事项。"
    user = f"""
分类: {category}
邮件发送时间: {sent_at.isoformat() if sent_at else ""}
默认时区: {settings.default_timezone}
Subject: {subject}
Body:
{body[:4500]}

输出 JSON schema:
{{
  "has_task": true,
  "title": "string",
  "description": "string",
  "due_at": "ISO datetime or null",
  "priority": "low | medium | high",
  "confidence": 0.0,
  "evidence": ["原文证据片段"]
}}
"""
    data = qwen_client.chat_json(model=settings.qwen_classifier_model, system=system, user=user, max_tokens=700)
    if not data or data.get("has_task") is False:
        return None
    return TaskCandidate(
        title=str(data.get("title") or subject or "邮件待办"),
        description=str(data.get("description") or ""),
        due_at=_parse_qwen_dt(data.get("due_at")),
        priority=str(data.get("priority") or "medium"),
        confidence=float(data.get("confidence") or 0.7),
        evidence=_list_str(data.get("evidence"))[:5],
    )


def _parse_qwen_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        parsed = dateparser.parse(
            value,
            languages=["zh", "en"],
            settings={
                "TIMEZONE": settings.default_timezone,
                "RETURN_AS_TIMEZONE_AWARE": True,
                "PREFER_DATES_FROM": "future",
            },
        )
    if not parsed:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(settings.default_timezone))
    return parsed


def _list_str(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _clean_optional(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
