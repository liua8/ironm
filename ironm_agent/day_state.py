"""今日状态（spec [2026-10-23] §54 需求 1）：会变的状态以表为准。

用户在对话里或首页说到今天的状态（累、没睡好、只有多少分钟、状态很好）时，作答前由规则写进今天这一份，
每条带时间和来源；每轮作答、首页今天的版本、管家今日调整都读同一份。共享档案第一段"今天"由这一份加上
打卡、生病、说疼的记录拼成。规则，不调用模型；内容加密存储，日志只记条数，不记内容。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from ironm_agent.casefile import said
from ironm_agent.ddl import run_ddl
from ironm_agent.training import PlanEdit

_log = logging.getLogger("ironm_agent.day_state")

type Kind = Literal["tired", "sleep", "minutes", "good"]
type Source = Literal["chat", "home"]

_TIRED = re.compile(r"有点累|很累|特别累|好累|太累|挺累|疲惫|疲劳|没劲|累死|没力气|浑身酸")
_POOR_NIGHT = re.compile(r"没睡好|失眠|熬夜|通宵|睡不着")
_SLEPT = re.compile(
    r"睡了?(?:不到)?\s*(\d+(?:\.\d+)?|[一二两三四五六七八九半])\s*(?:个)?\s*(?:多)?小时"
)
_GOOD = re.compile(
    r"状态(?:很|挺|特别|超)?(?:好|不错)|精神(?:很|挺)?(?:好|不错)|睡得(?:很|挺)?(?:好|香)"
)
_MINUTES = re.compile(
    r"(?:只有|就|只剩|只能练|能练)\s*(\d+|[一二两三四五六七八九十半]+)\s*(?:个)?\s*(分钟|小时|钟头)"
)
_CN = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def _number(raw: str) -> float | None:
    if raw.isdigit():
        return float(raw)
    if raw == "半":
        return 0.5
    if raw.endswith("半") and raw[:-1] in _CN:
        return _CN[raw[:-1]] + 0.5
    if raw.startswith("十") and len(raw) <= 2:
        return 10 + _CN.get(raw[1:], 0)
    return float(_CN[raw]) if raw in _CN else None


class Entry(BaseModel):
    kind: Kind
    at: datetime  # 说的时间
    source: Source = "chat"
    hours: float | None = None  # 睡了几小时（sleep）
    minutes: int | None = None  # 今天能练多少分钟（minutes）

    def text(self) -> str:
        when = self.at.astimezone().strftime("%H:%M")
        who = "首页点了" if self.source == "home" else "你说"
        what = {
            "tired": "今天有点累",
            "sleep": f"昨晚只睡了 {self.hours:g} 小时" if self.hours else "昨晚没睡好",
            "minutes": f"今天只有 {self.minutes} 分钟",
            "good": "今天状态不错",
        }[self.kind]
        return f"{what}（{when} {who}）"


class DayState(BaseModel):
    day: date
    entries: list[Entry] = Field(default_factory=list)
    edits: list[PlanEdit] = Field(default_factory=list)  # 计划页"只改今天"的改动，按先后（§106）

    def latest(self, kind: Kind) -> Entry | None:
        return next((e for e in reversed(self.entries) if e.kind == kind), None)

    def tired(self) -> Entry | None:
        """今天说过累或没睡好、之后没说状态好的那一条（只是他说的事实，怎么练由管家定，§182）。"""
        bad = max(
            (e for e in (self.latest("tired"), self.latest("sleep")) if e is not None),
            key=lambda e: e.at,
            default=None,
        )
        good = self.latest("good")
        return bad if bad is not None and (good is None or good.at < bad.at) else None

    def minutes(self) -> int | None:
        e = self.latest("minutes")
        return e.minutes if e is not None else None


def detect(text: str, at: datetime, source: Source = "chat") -> list[Entry]:
    """这句话里本人说到的今天的状态（否定的、说旁人的不算）。"""
    out: list[Entry] = []
    if said(_TIRED, text):
        out.append(Entry(kind="tired", at=at, source=source))
    m = _SLEPT.search(text)
    hours = _number(m.group(1)) if m else None
    if hours is not None and hours < 6 and said(_SLEPT, text):
        out.append(Entry(kind="sleep", at=at, source=source, hours=hours))
    elif said(_POOR_NIGHT, text):
        out.append(Entry(kind="sleep", at=at, source=source))
    m = _MINUTES.search(text)
    n = _number(m.group(1)) if m else None
    if m and n is not None:
        minutes = int(n * 60) if m.group(2) in ("小时", "钟头") else int(n)
        if 10 <= minutes <= 180:
            out.append(Entry(kind="minutes", at=at, source=source, minutes=minutes))
    if said(_GOOD, text):
        out.append(Entry(kind="good", at=at, source=source))
    return out


def lines(
    state: DayState | None,
    *,
    today: date,
    plan_name: str | None,
    checkins: Sequence[Any] = (),
    illness: str = "",
    pains: Sequence[tuple[str, date]] = (),
) -> list[str]:
    """共享档案第一段"今天"：每条写明时间或来源。checkins：今天的打卡（StoredLog）。"""
    out = []
    if plan_name is None:
        out.append("按计划：休息")
    else:
        out.append(f"按计划：{plan_name}")
    done = [c for c in checkins if c.log.day == today and c.log.done]
    for c in done:
        at = c.created.astimezone().strftime("%H:%M")
        bits = [
            f"感受 {c.log.rpe} 分" if c.log.rpe else "",
            f"{c.log.minutes} 分钟" if c.log.minutes else "",
        ]
        if c.log.state():  # 打卡记的精力、睡眠、哪里酸（§105）
            bits.append(c.log.state())
        extra = "，".join(b for b in bits if b)
        out.append(f"已打卡：{c.log.session or '训练'}（{at}{'，' + extra if extra else ''}）")
    for c in checkins:
        if c.log.day == today and getattr(c.log, "rest", None):  # 今天记了没练（§105）
            out.append(f"今天记了没练：{c.log.line().split(' ', 1)[-1]}")
    if not done and plan_name is not None:
        out.append("还没打卡")
    if state is not None:
        for kind in ("tired", "sleep", "good", "minutes"):
            e = state.latest(kind)
            if e is not None:
                out.append(e.text())
        if state.edits:  # 计划页"只改今天"（§106）
            out.append(
                "今天在计划页改过（只改今天）：" + "；".join(e.line for e in state.edits if e.line)
            )
    if illness:
        out.append(illness)
    if pains:
        parts = "、".join(dict.fromkeys(f"{p}（{d.month}-{d.day}）" for p, d in pains))
        out.append(f"最近说疼的部位：{parts}")
    return out


# ---- 存储 -----------------------------------------------------------------------------------


class DayStore(Protocol):
    async def get(self, user_id: str, day: date) -> DayState | None: ...
    async def add(self, user_id: str, day: date, entries: Sequence[Entry]) -> DayState: ...
    async def set_edits(self, user_id: str, day: date, edits: Sequence[PlanEdit]) -> DayState: ...


class DayBook:
    """内存版（测试与考题用）。"""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, date], DayState] = {}

    async def get(self, user_id: str, day: date) -> DayState | None:
        return self.rows.get((user_id, day))

    async def add(self, user_id: str, day: date, entries: Sequence[Entry]) -> DayState:
        state = self.rows.get((user_id, day)) or DayState(day=day)
        state = state.model_copy(update={"entries": [*state.entries, *entries]})
        self.rows[(user_id, day)] = state
        return state

    async def set_edits(self, user_id: str, day: date, edits: Sequence[PlanEdit]) -> DayState:
        state = self.rows.get((user_id, day)) or DayState(day=day)
        state = state.model_copy(update={"edits": list(edits)})
        self.rows[(user_id, day)] = state
        return state


DDL = """
CREATE TABLE IF NOT EXISTS ironm_day_state (
    user_id    text NOT NULL,
    day        date NOT NULL,
    content    text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, day)
)
"""


class PgDay:
    """数据库版：内容用 mirobody 的加密函数加密；同一个人同一天一行。"""

    def __init__(self) -> None:
        self._ready = False

    async def _q(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        from mirobody.utils.db import execute_query

        if not self._ready:
            await run_ddl(DDL)
            self._ready = True
        rows = await execute_query(sql, params, log_sql=False)
        return rows if isinstance(rows, list) else []

    async def get(self, user_id: str, day: date) -> DayState | None:
        rows = await self._q(
            "SELECT decrypt_content(content) AS content FROM ironm_day_state"
            " WHERE user_id = :uid AND day = :day",
            {"uid": user_id, "day": day},
        )
        return DayState.model_validate_json(rows[0]["content"]) if rows else None

    async def add(self, user_id: str, day: date, entries: Sequence[Entry]) -> DayState:
        state = await self.get(user_id, day) or DayState(day=day)
        return await self._save(
            user_id, state.model_copy(update={"entries": [*state.entries, *entries]})
        )

    async def set_edits(self, user_id: str, day: date, edits: Sequence[PlanEdit]) -> DayState:
        state = await self.get(user_id, day) or DayState(day=day)
        return await self._save(user_id, state.model_copy(update={"edits": list(edits)}))

    async def _save(self, user_id: str, state: DayState) -> DayState:
        await self._q(
            "INSERT INTO ironm_day_state (user_id, day, content) VALUES (:uid, :day, encrypt_content(:c))"
            " ON CONFLICT (user_id, day) DO UPDATE SET content = EXCLUDED.content, updated_at = now()",
            {"uid": user_id, "day": state.day, "c": state.model_dump_json()},
        )
        _log.info("day state saved: entries=%d edits=%d", len(state.entries), len(state.edits))
        return state


_default: DayStore | None = None


def default_day() -> DayStore:
    global _default
    if _default is None:
        _default = PgDay()
    return _default


async def note(
    store: DayStore, user_id: str, text: str, at: datetime, source: Source = "chat"
) -> tuple[DayState | None, list[Entry]]:
    """读今天这一份，把这句话里说到的状态写进去；返回（写完的今日状态, 这次新写的）。读写失败当作没有。"""
    day = at.astimezone().date()
    new = detect(text, at, source)
    try:
        if new:
            return await store.add(user_id, day, new), new
        return await store.get(user_id, day), []
    except Exception as e:
        _log.warning("day state unavailable: error_type=%s", type(e).__name__)
        return None, new
