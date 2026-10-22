"""对话记忆：从 mirobody 的对话记录里读本会话最近几轮，只用来理解指代。"""

from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger("ironm_agent.memory")

TURNS = 4  # 只取用户最近几句话，用来理解指代


def split_thread(session_id: str) -> tuple[str, str]:
    """mirobody 传进来的会话编号是"提问人:会话"，拆成两段。"""
    owner, _, session = session_id.partition(":")
    return (owner, session) if session else ("", session_id)


async def recent(session_id: str, current: str, turns: int = TURNS) -> list[str]:
    """用户最近说过的几句话（不含教练的回答，避免每次都把旧话题带进来）；读不到时返回空列表。"""
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
        if row.get("role") != "user" or not isinstance(content, str) or not content.strip():
            continue
        lines.append(f"用户：{content.strip()[:200]}")
    if lines and lines[-1] == f"用户：{current.strip()[:200]}":
        lines.pop()  # 本轮的问题已经先存进去了
    return lines[-turns:]
