from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.models import AgentRun, MailAccount
from app.services.agent_log import append_agent_log
from app.services.agent_tools import (
    ToolResult,
    available_tools_spec,
    collect_heuristic_context,
    compact_tool_result,
    run_agent_tool,
)
from app.services.qwen import qwen_client


MAX_AGENT_STEPS = 4


@dataclass
class AgentResponse:
    answer: str
    source_refs: list[dict[str, Any]]
    last_sync_at: datetime | None
    jsonl_ref: str | None
    run_id: int
    model_name: str
    tool_trace: list[dict[str, Any]]


def answer_question(db: Session, user_id: int, question: str) -> AgentResponse:
    run = AgentRun(
        user_id=user_id,
        run_type="interactive_query",
        status="running",
        input_text=question,
        model_name=settings.qwen_agent_model if qwen_client.enabled else "rules",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    append_agent_log(run.id, "user_query", {"question": question})
    last_sync_at = _last_sync_at(db, user_id)
    tool_results: list[ToolResult] = []
    source_refs: list[dict[str, Any]] = []

    try:
        if qwen_client.enabled:
            answer = _run_qwen_agent(db, user_id, question, last_sync_at, tool_results, run.id)
            if not answer:
                answer = _run_fallback_agent(db, user_id, question, tool_results)
                run.model_name = "rules_fallback"
        else:
            answer = _run_fallback_agent(db, user_id, question, tool_results)

        for result in tool_results:
            source_refs.extend(result.source_refs)
        source_refs = _dedupe_refs(source_refs)
        if last_sync_at:
            answer = f"{answer.rstrip()}\n\n最近一次邮件同步：{last_sync_at.strftime('%Y-%m-%d %H:%M:%S')}。"
        else:
            answer = f"{answer.rstrip()}\n\n还没有同步过邮件，请先点击前端“同步邮件”按钮。"

        run.status = "completed"
        run.output_text = answer
        run.summary = _summary_from_tools(tool_results)
        db.commit()

        trace = [compact_tool_result(result, max_items=5) for result in tool_results]
        jsonl_ref = append_agent_log(
            run.id,
            "agent_answer",
            {
                "answer": answer,
                "source_refs": source_refs,
                "tool_trace": trace,
                "model_name": run.model_name,
            },
        )
        run.jsonl_ref = jsonl_ref
        db.commit()
        return AgentResponse(answer, source_refs, last_sync_at, jsonl_ref, run.id, run.model_name, trace)
    except Exception as exc:
        db.rollback()
        run.status = "failed"
        run.output_text = f"Agent 执行失败：{exc}"
        db.commit()
        append_agent_log(run.id, "agent_error", {"error": str(exc)})
        return AgentResponse(run.output_text, [], last_sync_at, run.jsonl_ref, run.id, run.model_name or "unknown", [])


def _run_qwen_agent(
    db: Session,
    user_id: int,
    question: str,
    last_sync_at: datetime | None,
    tool_results: list[ToolResult],
    run_id: int,
) -> str | None:
    for step in range(MAX_AGENT_STEPS):
        planner = qwen_client.chat_json(
            model=settings.qwen_agent_model,
            system=_planner_system_prompt(),
            user=_planner_user_prompt(question, last_sync_at, tool_results),
            max_tokens=1200,
        )
        append_agent_log(run_id, "planner_response", {"step": step + 1, "response": planner or {}})
        if not planner:
            return None

        final_answer = _clean_str(planner.get("final_answer"))
        if final_answer:
            return final_answer

        calls = planner.get("tool_calls")
        if not isinstance(calls, list) or not calls:
            break

        ran_any = False
        for raw_call in calls[:3]:
            if not isinstance(raw_call, dict):
                continue
            tool_name = _clean_str(raw_call.get("tool_name") or raw_call.get("name"))
            arguments = raw_call.get("arguments") if isinstance(raw_call.get("arguments"), dict) else {}
            if not tool_name:
                continue
            result = run_agent_tool(db, user_id, tool_name, arguments, question)
            tool_results.append(result)
            append_agent_log(
                run_id,
                "tool_result",
                {
                    "step": step + 1,
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "preview": result.preview,
                    "source_refs": result.source_refs,
                },
            )
            ran_any = True
        if not ran_any:
            break

    return _synthesize_with_qwen(question, last_sync_at, tool_results)


def _run_fallback_agent(db: Session, user_id: int, question: str, tool_results: list[ToolResult]) -> str:
    tool_results.extend(collect_heuristic_context(db, user_id, question))
    return _synthesize_locally(question, tool_results)


def _synthesize_with_qwen(question: str, last_sync_at: datetime | None, tool_results: list[ToolResult]) -> str | None:
    if not qwen_client.enabled or not tool_results:
        return None
    data = qwen_client.chat_json(
        model=settings.qwen_agent_model,
        system=(
            "你是一个个人邮件日程 Agent。基于工具结果回答用户问题。"
            "不要编造工具结果里没有的信息；如果没有找到，明确说明。"
            "回答要简洁、可执行，中文输出。只输出 JSON。"
        ),
        user=json.dumps(
            {
                "question": question,
                "last_sync_at": last_sync_at.isoformat() if last_sync_at else None,
                "tool_results": [compact_tool_result(result) for result in tool_results],
                "output_schema": {"answer": "string"},
            },
            ensure_ascii=False,
            default=str,
        ),
        max_tokens=1400,
    )
    if not data:
        return None
    return _clean_str(data.get("answer"))


def _synthesize_locally(question: str, tool_results: list[ToolResult]) -> str:
    lines = [f"问题：{question}", ""]
    event_items: list[dict[str, Any]] = []
    task_items: list[dict[str, Any]] = []
    mail_items: list[dict[str, Any]] = []
    conflict_items: list[dict[str, Any]] = []
    other_previews: list[str] = []

    for result in tool_results:
        if result.tool_name == "event.query" and isinstance(result.data, list):
            event_items.extend(result.data)
        elif result.tool_name == "task.query" and isinstance(result.data, list):
            task_items.extend(result.data)
        elif result.tool_name == "mail.search" and isinstance(result.data, list):
            mail_items.extend(result.data)
        elif result.tool_name == "conflict.query" and isinstance(result.data, list):
            conflict_items.extend(result.data)
        else:
            other_previews.append(result.preview)

    if event_items:
        lines.append(f"找到 {len(event_items)} 个相关日程：")
        for event in event_items[:20]:
            start = event.get("start_time") or "时间待确认"
            title = event.get("title") or "未命名日程"
            status = event.get("status") or "unknown"
            place = event.get("meeting_link") or event.get("location") or ""
            suffix = f"；{place}" if place else ""
            lines.append(f"- {start}｜{title}｜状态：{status}{suffix}")

    if task_items:
        if lines[-1] != "":
            lines.append("")
        lines.append(f"找到 {len(task_items)} 个待办：")
        for task in task_items[:20]:
            due = task.get("due_at") or "无截止时间"
            lines.append(f"- {task.get('title') or '未命名待办'}｜{due}｜优先级：{task.get('priority')}")

    if conflict_items:
        if lines[-1] != "":
            lines.append("")
        lines.append(f"找到 {len(conflict_items)} 个日程冲突：")
        for conflict in conflict_items[:20]:
            lines.append(f"- {conflict.get('description') or conflict.get('conflict_type')}｜严重程度：{conflict.get('severity')}")

    if mail_items and not event_items:
        if lines[-1] != "":
            lines.append("")
        lines.append(f"找到 {len(mail_items)} 封相关邮件：")
        for email in mail_items[:10]:
            category = email.get("category") or "未分类"
            lines.append(f"- #{email.get('id')} {email.get('subject') or '(无标题)'}｜{email.get('from_email') or ''}｜{category}")

    if not event_items and not task_items and not mail_items and not conflict_items:
        lines.append("本地数据库暂时没有找到足够的信息回答这个问题。你可以先同步邮件，或换一个更具体的关键词。")

    if other_previews:
        lines.append("")
        lines.extend(other_previews[:3])
    return "\n".join(lines).strip()


def _planner_system_prompt() -> str:
    return (
        "你是一个本地邮件日程 Agent 的规划器。你只能基于工具结果回答，不能编造邮件、时间、链接或公司。"
        "你可以多步调用工具。每次只输出 JSON，不要输出 Markdown。"
        "如果已有工具结果足够回答，输出 final_answer；否则输出 tool_calls。"
        "可用工具如下："
        + json.dumps(available_tools_spec(), ensure_ascii=False)
        + "\n输出格式二选一："
        + json.dumps(
            {
                "thought": "简短说明下一步",
                "tool_calls": [{"tool_name": "event.query", "arguments": {"days_ahead": 7}}],
                "final_answer": None,
            },
            ensure_ascii=False,
        )
        + " 或 "
        + json.dumps({"thought": "已可回答", "tool_calls": [], "final_answer": "给用户的中文回答"}, ensure_ascii=False)
    )


def _planner_user_prompt(question: str, last_sync_at: datetime | None, tool_results: list[ToolResult]) -> str:
    return json.dumps(
        {
            "question": question,
            "last_sync_at": last_sync_at.isoformat() if last_sync_at else None,
            "tool_results_so_far": [compact_tool_result(result) for result in tool_results],
            "instruction": "先判断需要哪些本地工具。涉及相对日期时调用 time.now 或直接给 event.query 合理时间窗口。",
        },
        ensure_ascii=False,
        default=str,
    )


def _last_sync_at(db: Session, user_id: int) -> datetime | None:
    account = db.query(MailAccount).filter(MailAccount.user_id == user_id).order_by(MailAccount.last_sync_at.desc()).first()
    return account.last_sync_at if account else None


def _summary_from_tools(tool_results: list[ToolResult]) -> str:
    if not tool_results:
        return "no tools"
    return "; ".join(f"{result.tool_name}: {result.preview}" for result in tool_results[:8])


def _dedupe_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, Any]] = set()
    out: list[dict[str, Any]] = []
    for ref in refs:
        key = (ref.get("type"), ref.get("id"))
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
