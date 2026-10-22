"""把这一轮的结果转成 mirobody 网页认识的流式块。

每个参与的 Agent 显示为一对"工具调用 / 结果"（网页上可以展开）；正文是一个 text 块，
引用健康数据的句子用 mirobody 的 <statement>…<cite>[r3]</cite></statement> 格式，网页上可以点开。
"""

from __future__ import annotations

from typing import Any

from ironm_agent.checks import EXPERIENCE, plain
from ironm_agent.compose import Composed
from ironm_agent.experts import Consultation
from ironm_agent.safety.replies import ReplySection

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
        lines.append(f"结论：{c.opinion.conclusion}")
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
