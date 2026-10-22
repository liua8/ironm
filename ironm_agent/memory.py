"""对话记忆：从 mirobody 的对话记录里读本会话最近几轮，只用来理解指代。"""

from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger("ironm_agent.memory")

TURNS = 6


def split_thread(session_id: str) -> tuple[str, str]:
    """mirobody 传进来的会话编号是"提问人:会话"，拆成两段。"""
    owner, _, session = session_id.partition(":")
    return (owner, session) if session else ("", session_id)


async def recent(session_id: str, current: str, turns: int = TURNS) -> list[str]:
    """最近几轮对话，格式为"用户：…""教练：…"；读不到时返回空列表。"""
    owner, session = split_thread(session_id)
    if not owner or not session:
        return []
    try:
        from mirobody.agent.chat.message import get_chat_history

        rows: list[dict[str, Any]] = await get_chat_history(owner, session)
    except Exception as e:  # 读不到历史不影响作答
        _log.warning("history unavailable: error_type=%s", type(e).__name__)
        return []
    lines = []
    for row in rows:
        content = row.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        who = "用户" if row.get("role") == "user" else "教练"
        lines.append(f"{who}：{content.strip()[:300]}")
    if lines and lines[-1] == f"用户：{current.strip()[:300]}":
        lines.pop()  # 本轮的问题已经先存进去了
    return lines[-turns * 2 :]
