from __future__ import annotations

from dataclasses import dataclass

from app.config import settings
from app.services.qwen import qwen_client


@dataclass
class ClassificationResult:
    category: str
    confidence: float
    reason: str
    evidence: list[str]
    model_name: str = "rules"


KEYWORDS = {
    "interview": ["面试", "一面", "二面", "终面", "技术面", "hr面", "interview"],
    "written_test": ["笔试", "测评", "在线测试", "assessment", "test invitation", "coding test"],
    "offer": ["offer", "录用", "薪资", "意向书"],
    "rejection": ["遗憾", "不匹配", "未通过", "rejected", "unfortunately"],
    "deadline": ["截止", "deadline", "ddl", "due"],
    "todo_request": ["请你", "需要你", "麻烦", "提交", "回复", "确认"],
    "meeting_invite": ["会议", "meeting", "zoom", "腾讯会议", "飞书会议", "teams"],
}


def classify_email(subject: str, sender: str | None, clean_text: str) -> ClassificationResult:
    content = f"{subject}\n{sender or ''}\n{clean_text[:4000]}".lower()
    for category, keywords in KEYWORDS.items():
        hits = [kw for kw in keywords if kw.lower() in content]
        if hits:
            return ClassificationResult(
                category=category,
                confidence=0.82,
                reason=f"规则命中关键词：{', '.join(hits[:5])}",
                evidence=hits[:5],
            )

    qwen_result = _classify_with_qwen(subject, sender, clean_text)
    if qwen_result:
        return qwen_result

    return ClassificationResult(
        category="notification",
        confidence=0.45,
        reason="未命中高价值事务关键词，默认作为普通通知处理。",
        evidence=[],
    )


def _classify_with_qwen(subject: str, sender: str | None, clean_text: str) -> ClassificationResult | None:
    system = (
        "你是邮件分类器。只输出 JSON。可用类别：interview, written_test, meeting_invite, "
        "offer, rejection, hr_followup, todo_request, calendar_update, deadline, notification, newsletter, spam_like, unknown。"
    )
    user = f"""
请分类这封邮件，并给出 confidence、reason、evidence。

Subject: {subject}
Sender: {sender or ""}
Body:
{clean_text[:3500]}
"""
    data = qwen_client.chat_json(
        model=settings.qwen_classifier_model,
        system=system,
        user=user,
        max_tokens=512,
    )
    if not data:
        return None
    category = str(data.get("category") or "unknown")
    confidence = float(data.get("confidence") or 0.5)
    reason = str(data.get("reason") or "Qwen 分类")
    evidence = data.get("evidence") if isinstance(data.get("evidence"), list) else []
    return ClassificationResult(category=category, confidence=confidence, reason=reason, evidence=evidence, model_name=settings.qwen_classifier_model)
