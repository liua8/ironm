"""把这一轮的结果转成 mirobody 网页认识的流式块。

每个参与的 Agent 显示为一对"工具调用 / 结果"（网页上可以展开）；正文是一个 text 块，
引用健康数据的句子用 mirobody 的 <statement>…<cite>[r3]</cite></statement> 格式，网页上可以点开。
"""

from __future__ import annotations

import json
from typing import Any

from ironm_agent.checks import EXPERIENCE, plain
from ironm_agent.compose import Composed
from ironm_agent.experts import Consultation
from ironm_agent.safety.replies import ReplySection
from ironm_agent.training import Draft, Plan, WorkoutLog, weekday_name

STATUS = {"spoke": "写出了意见", "silent": "没能给出意见", "failed": "没能作答（模型不可用）"}


def started(call_id: str, name: str, task: str) -> dict[str, Any]:
    return {"type": "tool_call", "id": call_id, "name": name, "args": {"任务": task}}


def finished(call_id: str, content: str, *, ok: bool = True) -> dict[str, Any]:
    return {
        "type": "tool_result",
        "tool_call_id": call_id,
        "content": content,
        "status": "ok" if ok else "error",
    }


def consultation_summary(c: Consultation) -> str:
    ev = c.evidence
    lines = [STATUS[c.status]]
    if not c.opinion.speak and c.opinion.reason:
        lines.append(f"原因：{c.opinion.reason}")
    if ev.health_queries:
        lines.append(
            f"查询健康数据 {ev.health_queries} 次" + ("（读取失败）" if ev.health_failed else "")
        )
    if ev.knowledge_queries:
        lines.append(f"查询依据库 {ev.knowledge_queries} 次，查到：{'、'.join(ev.entries) or '无'}")
    if c.opinion.speak:
        first = c.opinion.conclusion or plain(c.opinion.answer).split("。")[0]
        lines.append(f"结论：{first[:60]}")
    return "\n".join(lines)


def notice(text: str) -> dict[str, Any]:
    return {"type": "notice", "text": text}


def text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def sections_text(sections: tuple[ReplySection, ...]) -> str:
    return "\n\n".join(f"**{s.title}**\n{s.text}" for s in sections)


def answer_text(composed: Composed, *, prefix: str = "") -> str:
    """正文：精炼的回答本身，不带出处标记（出处在“依据与来源”里）。"""
    return "\n\n".join(p for p in (prefix, plain(composed.text)) if p)


SOURCES_ID = "sources"
TURN_ID = "turn"  # 这一轮的编号（页面评价时带回，spec [2026-10-23] §31），页面上不显示
SOURCES_NAME = "依据与来源"


def sources_text(composed: Composed) -> str:
    """这条回答用到的资料、计算、个人数据和经验部分；放在可展开的“依据与来源”里。"""
    parts: list[str] = []
    if composed.rows:
        parts.append("你的数据：\n" + "\n".join(f"- {desc}" for _, desc in composed.rows))
    if composed.calcs:
        parts.append("计算：\n" + "\n".join(f"- {detail}" for _, detail in composed.calcs))
    if composed.entries:
        parts.append(
            "资料：\n"
            + "\n".join(f"- {e.cite_label().split('〕', 1)[1]}" for e in composed.entries)
        )
    if EXPERIENCE in composed.text:
        parts.append("经验：部分建议来自教练的专业经验，依据库里暂时没有对应的资料。")
    return "\n\n".join(parts)


# ---- 预览卡片（spec [2026-10-23] §9）：一对"工具调用 / 结果"，id 以 card- 开头，网页显示成可以确认的卡片 ----


def _card(draft: Draft, title: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    cid = f"card-{draft.id}"
    content = {
        "kind": draft.kind,
        "draft": draft.id,
        "title": title,
        "expires": draft.json()["expires"],
        **body,
    }
    return [
        {"type": "tool_call", "id": cid, "name": title, "args": {"kind": draft.kind, "draft": draft.id}},
        {"type": "tool_result", "tool_call_id": cid, "content": json.dumps(content, ensure_ascii=False), "status": "ok"},
    ]  # fmt: skip


def plan_card(draft: Draft, plan: Plan, current: Plan | None) -> list[dict[str, Any]]:
    before = {s.day: s.name for s in current.sessions} if current else {}
    sessions = [
        {
            "day": weekday_name(s.day),
            "name": s.name,
            "minutes": s.minutes,
            "items": [x.line() for x in s.items],
            "changed": before.get(s.day) != s.name,
        }
        for s in plan.sessions
    ]
    gone = [
        f"{weekday_name(d)} {n}"
        for d, n in before.items()
        if d not in {s.day for s in plan.sessions}
    ]
    body = {
        "headline": f"《{plan.title}》每周 {plan.days_per_week} 练"
        + (f" · {plan.goal}" if plan.goal else ""),
        "changes": str(draft.content.get("changes") or ""),
        "sessions": sessions,
        "removed": gone,
        "replaces": bool(current),
    }
    return _card(draft, "计划预览", body)


def log_card(draft: Draft, log: WorkoutLog) -> list[dict[str, Any]]:
    body = {
        "headline": log.line(),
        "items": [x.line() for x in log.items],
        "rpe": log.rpe,
        "note": log.note,
    }
    return _card(draft, "训练记录预览", body)
