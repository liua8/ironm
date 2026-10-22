"""把这一轮的结果转成 mirobody 网页认识的流式块。

每个参与的 Agent 显示为一对"工具调用 / 结果"（网页上可以展开）；正文是一个 text 块，
引用健康数据的句子用 mirobody 的 <statement>…<cite>[r3]</cite></statement> 格式，网页上可以点开。
"""

from __future__ import annotations

from typing import Any

from ironm_agent.compose import Composed
from ironm_agent.experts import Consultation
from ironm_agent.safety.replies import ReplySection

STATUS = {"spoke": "写出了意见", "silent": "没有发言", "failed": "没能作答"}


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
    parts = [p for p in (prefix, composed.text) if p]
    if composed.safety:
        parts.append(f"**安全提醒**\n{composed.safety}")
    if composed.calcs:
        how = "\n".join(f"- 〔{cid}〕{detail}" for cid, detail in composed.calcs)
        parts.append(f"**怎么算的**\n{how}")
    if composed.entries:
        refs = "\n".join(f"- {e.cite_label()}" for e in composed.entries)
        parts.append(f"**参考资料**\n{refs}")
    return "\n\n".join(parts)
