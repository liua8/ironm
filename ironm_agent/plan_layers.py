"""计划分三层（spec [2026-10-23] §163 需求 2）：基础计划 + 临时调整 + 今天的版本。

临时调整是他确认过的、带开始和结束日期的一组改法（出差这三天换哑铃版、病后这一周减量……），存成预览卡片
（kind "temp"），他点确认才生效，确认后能撤销；没确认的过了开始日期作废。哪天在有效期里，那天的计划就是
基础计划套上这些改法；过了结束日期自动回到基础计划。改法每次读的时候重新套到当前的基础计划上：基础计划
后来改了、套不上的那条就不算（不替他猜）。只是机制，不判断要不要调——那是管家的事。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from ironm_agent.training import Plan

_log = logging.getLogger("ironm_agent.plan_layers")

MAX_DAYS = 28  # 临时调整最长多久（再长就是改基础计划了）


@dataclass(frozen=True)
class Temp:
    id: str
    start: date
    end: date
    why: str
    ops: tuple[dict[str, Any], ...]
    lines: tuple[str, ...] = ()

    def covers(self, day: date) -> bool:
        return self.start <= day <= self.end

    def line(self) -> str:
        span = f"{self.start.month}月{self.start.day}日" + (
            f"–{self.end.month}月{self.end.day}日" if self.end != self.start else ""
        )
        return f"{span}{('（' + self.why + '）') if self.why else ''}：{'；'.join(self.lines) or '按改法'}"


def of_draft(d: Any) -> Temp | None:
    """确认过的临时调整预览 → Temp；内容不对的不要。"""
    t = (getattr(d, "content", None) or {}).get("temp") or {}
    try:
        start, end = date.fromisoformat(str(t["start"])), date.fromisoformat(str(t["end"]))
    except (KeyError, ValueError):
        return None
    ops = tuple(x for x in t.get("ops") or [] if isinstance(x, dict))
    if not ops or end < start:
        return None
    return Temp(str(d.id), start, end, str(t.get("why") or ""), ops, tuple(str(x) for x in t.get("lines") or []))


def active(temps: Sequence[Temp], day: date) -> list[Temp]:
    return [t for t in temps if t.covers(day)]


def plan_on(plan: Plan | None, temps: Sequence[Temp], day: date) -> Plan | None:
    """这一天实际的计划：基础计划套上这天在有效期里的临时调整（按确认的先后）；套不上的跳过。"""
    from ironm_agent.plan_ops import Conflict, apply, parse_ops

    if plan is None:
        return None
    out = plan
    for t in active(temps, day):
        ops = parse_ops(list(t.ops))
        if not ops:
            continue
        try:
            got = apply(out, ops)
        except Conflict:
            _log.info("temp skipped: conflict")
            continue
        if got.done:
            out = got.plan
    return out


def content(start: date, end: date, why: str, applied: Any, lines: Sequence[str]) -> dict[str, Any]:
    """存进预览卡片的内容：网页沿用训练记录那种卡片（标题、一句说明、几行）。"""
    from ironm_agent.plan_ops import describe

    span = f"{start.month}月{start.day}日" + (f"到{end.month}月{end.day}日" if end != start else "")
    return {
        "title": "临时调整",
        "headline": f"{span}这样练，之后回到原计划" + (f"：{why}" if why else ""),
        "items": list(lines),
        "temp": {"start": start.isoformat(), "end": end.isoformat(), "why": why,
                 "ops": describe(applied)["ops"], "lines": list(lines)},
    }  # fmt: skip


async def load(store: Any, user_id: str) -> list[Temp]:
    """他确认过、还没结束的临时调整；读不到当作没有。"""
    try:
        drafts = await store.temps(user_id)
    except Exception as e:
        _log.warning("temps unavailable: error_type=%s", type(e).__name__)
        return []
    return [t for t in (of_draft(d) for d in drafts) if t is not None]
