"""会话内的短期记忆：从 mirobody 的对话记录里读本会话最近几轮，只用来理解指代（"上面说的"）。

带用户最近几句话，加上最近两条回答的要点（开头一小段），不带整条回答，免得把旧话题带进新问题。
跨会话的长期记忆见 memory_store / memory_view。
"""

from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger("ironm_agent.memory")

TURNS = 4  # 用户最近几句话
ANSWERS = 2  # 最近几条回答的要点
ANSWER_CHARS = 80  # 每条回答取开头多少字作为要点
USER = "用户："
COACH = "教练（要点）："


def split_thread(session_id: str) -> tuple[str, str]:
    """mirobody 传进来的会话编号是"提问人:会话"，拆成两段。"""
    owner, _, session = session_id.partition(":")
    return (owner, session) if session else ("", session_id)


def _gist(answer: str) -> str:
    """回答的要点：开头一小段（第一段里最多 ANSWER_CHARS 个字）。"""
    first = answer.strip().split("\n", 1)[0].strip()
    return first if len(first) <= ANSWER_CHARS else first[:ANSWER_CHARS] + "…"


def thread_lines(rows: list[dict[str, Any]], current: str, turns: int = TURNS) -> list[str]:
    """从对话记录里排出最近几轮：用户的原话，加上最近 ANSWERS 条回答的要点。"""
    lines: list[tuple[str, str]] = []
    for row in rows:
        content = row.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        if row.get("role") == "user":
            lines.append(("user", content.strip()[:200]))
        elif row.get("role") == "assistant":
            lines.append(("coach", _gist(content)))
    if lines and lines[-1] == ("user", current.strip()[:200]):
        lines.pop()  # 本轮的问题已经先存进去了
    users = [i for i, (who, _) in enumerate(lines) if who == "user"]
    if not users:
        return []
    kept = lines[users[-turns] if len(users) >= turns else users[0] :]
    coach = [i for i, (who, _) in enumerate(kept) if who == "coach"][-ANSWERS:]
    return [
        (USER if who == "user" else COACH) + text
        for i, (who, text) in enumerate(kept)
        if who == "user" or i in coach
    ]


async def recent(session_id: str, current: str, turns: int = TURNS) -> list[str]:
    """本会话最近几轮（用户原话 + 最近两条回答的要点）；读不到时返回空列表。"""
    owner, session = split_thread(session_id)
    if not owner or not session:
        return []
    try:
        from mirobody.agent.chat.message import get_chat_history

        rows: list[dict[str, Any]] = await get_chat_history(owner, session)
    except Exception as e:  # 读不到历史不影响作答
        _log.warning("history unavailable: error_type=%s", type(e).__name__)
        return []
    return thread_lines(rows, current, turns)


async def earlier(session_id: str) -> str:
    """本会话之前的全部回答原文（只用来判断某条固定提醒说过没有，不交给模型）；读不到时为空。"""
    owner, session = split_thread(session_id)
    if not owner or not session:
        return ""
    try:
        from mirobody.agent.chat.message import get_chat_history

        rows: list[dict[str, Any]] = await get_chat_history(owner, session)
    except Exception as e:
        _log.warning("history unavailable: error_type=%s", type(e).__name__)
        return ""
    return "\n".join(str(r.get("content") or "") for r in rows if r.get("role") == "assistant")


def user_lines(history: list[str]) -> list[str]:
    """只要用户自己说的话（记忆提取用：记忆只能来自用户的原话）。"""
    return [line for line in history if line.startswith(USER)]


async def last_sources(session_id: str, tool_call_id: str) -> str | None:
    """本会话上一条回答的“依据与来源”（存在 mirobody 的对话记录里）；没有时返回 None。"""
    owner, session = split_thread(session_id)
    if not owner or not session:
        return None
    try:
        from mirobody.agent.chat.message import get_chat_history

        rows: list[dict[str, Any]] = await get_chat_history(owner, session)
    except Exception as e:
        _log.warning("history unavailable: error_type=%s", type(e).__name__)
        return None
    from ironm_agent.provenance import is_explanation

    for row in reversed(rows):
        if row.get("role") == "user":
            continue
        if is_explanation(str(row.get("content") or "")):
            continue  # 上一次追问来源的回复，往前找真正的回答
        for block in row.get("content_dict") or []:
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_result"
                and block.get("tool_call_id") == tool_call_id
            ):
                return str(block.get("content") or "")
        return ""  # 上一条回答没有附来源
    return None
