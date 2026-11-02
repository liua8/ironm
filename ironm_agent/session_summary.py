"""会话摘要（spec [2026-10-23] §73 需求 4、6）：一个会话 3 句以上后在后台写 3–5 句，之后每多 4 句更新；
新会话开头带最近 2 个别的会话的摘要。摘要里答应的事变成待跟进（原话要能在对话里找到）。

摘要只当上下文，不进画像、不改计划；加密存储，日志只记条数和耗时。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

from ironm_agent.llm import LLM, ModelUnavailable, parse_json
from ironm_agent.memory_extract import MAX_CONTENT, norm, until_of
from ironm_agent.memory_store import Change, Item, new_id, now

_log = logging.getLogger("ironm_agent.session_summary")

FIRST = 3  # 用户说了几句之后写第一次
EVERY = 4  # 之后每多几句更新一次
SHOW = 2  # 新会话带几个别的会话的摘要
MAX_CHARS = 300

_PROMPT = """你替健身教练给刚才这段对话写一份摘要，下次和这个人聊天时用来接上话。只写对话里实际说过的，不推测、不加建议。

只输出 JSON：
{"summary": "3–5 句：聊了什么、定了什么（计划、调整、记录）、还没说完的、答应了什么",
 "promises": [{"content": "要跟进的事，一句话，如：问问左膝下楼还疼不疼", "due": "到期日 YYYY-MM-DD", "quote": "对话里一字不差的一段，能证明说过要跟进"}]}
promises 只写教练答应要回访、或用户要求提醒的事；没有就写空列表。due 按今天的日期算（"下周"写下周一，"两周后"写 14 天后）。"""


@dataclass(frozen=True)
class Summary:
    session: str
    text: str
    turns: int  # 写这份摘要时用户说了几句
    updated: datetime


class SummaryStore(Protocol):
    async def get(self, user_id: str, session: str) -> Summary | None: ...
    async def put(self, user_id: str, summary: Summary) -> None: ...
    async def latest(self, user_id: str, exclude: str, k: int) -> list[Summary]: ...


class SummaryBook:
    """内存版（测试用）。"""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], Summary] = {}

    async def get(self, user_id: str, session: str) -> Summary | None:
        return self.rows.get((user_id, session))

    async def put(self, user_id: str, summary: Summary) -> None:
        self.rows[(user_id, summary.session)] = summary

    async def latest(self, user_id: str, exclude: str, k: int) -> list[Summary]:
        mine = [s for (u, _), s in self.rows.items() if u == user_id and s.session != exclude]
        return sorted(mine, key=lambda s: s.updated, reverse=True)[:k]


DDL = """
CREATE TABLE IF NOT EXISTS ironm_session_summary (
    user_id    text NOT NULL,
    session    text NOT NULL,
    summary    text NOT NULL,
    turns      integer NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, session)
)
"""


class PgSummary:
    """数据库版：摘要和 mirobody 对话内容同一种加密。"""

    def __init__(self) -> None:
        self._ready = False

    async def _q(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        from mirobody.utils.db import execute_query

        if not self._ready:
            await execute_query(DDL, {}, log_sql=False)
            self._ready = True
        rows = await execute_query(sql, params, log_sql=False)
        return rows if isinstance(rows, list) else []

    @staticmethod
    def _row(r: dict[str, Any]) -> Summary:
        return Summary(
            str(r["session"]), str(r.get("summary") or ""), int(r["turns"]), r["updated_at"]
        )

    async def get(self, user_id: str, session: str) -> Summary | None:
        got = await self._q(
            "SELECT session, decrypt_content(summary) AS summary, turns, updated_at"
            " FROM ironm_session_summary WHERE user_id = :uid AND session = :s",
            {"uid": user_id, "s": session},
        )
        return self._row(got[0]) if got else None

    async def put(self, user_id: str, summary: Summary) -> None:
        await self._q(
            "INSERT INTO ironm_session_summary (user_id, session, summary, turns, updated_at)"
            " VALUES (:uid, :s, encrypt_content(:text), :turns, now())"
            " ON CONFLICT (user_id, session) DO UPDATE SET summary = EXCLUDED.summary,"
            " turns = EXCLUDED.turns, updated_at = now()",
            {"uid": user_id, "s": summary.session, "text": summary.text, "turns": summary.turns},
        )

    async def latest(self, user_id: str, exclude: str, k: int) -> list[Summary]:
        got = await self._q(
            "SELECT session, decrypt_content(summary) AS summary, turns, updated_at"
            " FROM ironm_session_summary WHERE user_id = :uid AND session <> :s"
            " ORDER BY updated_at DESC LIMIT :k",
            {"uid": user_id, "s": exclude, "k": k},
        )
        return [self._row(r) for r in got]


_default: SummaryStore | None = None


def default_summaries() -> SummaryStore:
    global _default
    if _default is None:
        _default = PgSummary()
    return _default


def due(previous: Summary | None, turns: int) -> bool:
    """该不该写（或更新）摘要：用户说了 3 句以上，且比上次写的时候多了 4 句以上。"""
    if turns < FIRST:
        return False
    return previous is None or turns - previous.turns >= EVERY


def promises(raw: Any, lines: Sequence[str], today: date, existing: Sequence[Item]) -> list[Change]:
    """摘要里答应的事 → 待跟进。原话要能在对话里找到；和还没到期的待跟进重复的不要。"""
    if not isinstance(raw, list):
        return []
    said = norm("\n".join(lines))
    have = {norm(x.content) for x in existing if x.category == "followup" and x.status == "active"}
    out: list[Change] = []
    for p in raw[:3]:
        if not isinstance(p, dict):
            continue
        content = str(p.get("content") or "").strip()
        quote = str(p.get("quote") or "").strip()
        day = until_of(p.get("due"), today)
        if not content or len(content) > MAX_CONTENT or day is None:
            continue
        if len(norm(quote)) < 2 or norm(quote) not in said or norm(content) in have:
            continue
        at = now()
        out.append(Change("insert", item=Item(new_id(), "followup", content, quote, "said", "active",
                                              at, at, None, day)))  # fmt: skip
        have.add(norm(content))
    return out


async def summarize(
    llm: LLM, lines: Sequence[str], today: date, existing: Sequence[Item]
) -> tuple[str, list[Change]]:
    """调一次模型写摘要；模型不可用或输出不对时返回空，不向外抛。"""
    messages = [
        {"role": "system", "content": _PROMPT},
        {"role": "user", "content": f"今天是 {today.isoformat()}。\n对话：\n" + "\n".join(lines)},
    ]
    try:
        reply = await llm.chat("memory", messages, json_mode=True)
    except ModelUnavailable:
        return "", []
    raw = parse_json(reply.content) or {}
    text = " ".join(str(raw.get("summary") or "").split())[:MAX_CHARS]
    return text, promises(raw.get("promises"), lines, today, existing) if text else []
