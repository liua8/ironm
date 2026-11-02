"""时间线（spec [2026-10-23] §97）：把最近一段时间散在各处的事按日期排在一起，只读。

来源：生病记录（开始、好了）、记忆里的伤病和近期事件（说的哪天、到哪天、不再适用）、说疼的部位、
训练记录、管家的调整（调了什么、原因、到期核对的效果）。用来回答"上周为什么给我减量了""这个月发生了什么"。
读不到的那一类跳过；日志只记条数。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import date, timedelta
from typing import Any

_log = logging.getLogger("ironm_agent.run")

DEFAULT_DAYS, MAX_DAYS, MAX_LINES = 28, 90, 80
_KINDS = {"injury": "伤病", "event": "近期的事"}

SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "timeline",
        "description": (
            "查这个人最近一段时间发生了什么：生病和好了、伤病和近期的事、说疼的部位、训练记录、管家做过的调整（原因和效果）。"
            '回答"上周为什么给我减量了""这个月怎么样""最近发生了什么"时用。'
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "days": {"type": "integer", "description": "往前看几天，默认 28，最多 90"}
            },
        },
    },
}


def _md(d: date) -> str:
    return f"{d.month}月{d.day}日"


async def _safely(what: str, coro: Awaitable[Any]) -> Any:
    try:
        return await coro
    except Exception as e:  # 某一类读不到：跳过，其余照常
        _log.info("timeline part unavailable: part=%s error_type=%s", what, type(e).__name__)
        return None


def build(
    today: date,
    days: int,
    *,
    illness: Sequence[Any] = (),
    memory: Sequence[Any] = (),
    pains: Sequence[tuple[str, date]] = (),
    workouts: Sequence[Any] = (),
    changes: Sequence[Any] = (),
) -> list[str]:
    """按日期排好的时间线（新的在后）。"""
    start = today - timedelta(days=days - 1)
    rows: list[tuple[date, int, str]] = []
    for ep in illness:
        if start <= ep.started <= today:
            rows.append((ep.started, 0, f"说{ep.what()}"))
        if ep.ended is not None and start <= ep.ended <= today:
            rows.append((ep.ended, 0, f"{ep.what()}好了"))
    for x in memory:
        if x.category not in _KINDS:
            continue
        said = x.created.astimezone().date()
        if start <= said <= today:
            until = f"，到{_md(x.until)}" if x.until is not None else ""
            rows.append((said, 1, f"{_KINDS[x.category]}：{x.content}{until}"))
        ended = x.updated.astimezone().date()
        if x.status != "active" and start <= ended <= today:
            rows.append((ended, 1, f"{_KINDS[x.category]}不再适用：{x.content}"))
    for part, d in pains:
        if start <= d <= today:
            rows.append((d, 2, f"说{part}疼"))
    for log in workouts:
        if start <= log.day <= today and log.done:
            rows.append((log.day, 3, "练了：" + log.line().split(" ", 1)[-1]))
    seen: set[tuple[str, date, str]] = set()
    for c in changes:
        k = (c.key, c.day, c.after)
        if (
            k in seen
            or c.change not in ("added", "changed", "declined")
            or not (start <= c.day <= today)
        ):
            continue
        seen.add(k)
        if c.change == "declined":
            rows.append((c.day, 4, f"管家的调整被撤销：{c.after}"))
            continue
        why = f"（原因：{c.why}）" if c.why else ""
        effect = f"；效果：{c.outcome}" if c.outcome else ""
        rows.append((c.day, 4, f"管家：{c.after}{why}{effect}"))
    rows.sort(key=lambda r: (r[0], r[1]))
    lines = [f"{_md(d)} {text}" for d, _, text in rows][-MAX_LINES:]
    return lines


def tool(
    today: date,
    *,
    illness: Callable[[date], Awaitable[Sequence[Any]]] | None = None,
    memory: Sequence[Any] = (),
    pains: Callable[[date], Awaitable[Sequence[tuple[str, date]]]] | None = None,
    workouts: Callable[[date], Awaitable[Sequence[Any]]] | None = None,
    changes: Callable[[], Awaitable[Sequence[Any]]] | None = None,
) -> Any:
    """给管家的时间线工具（只读）。"""

    async def run(box: Any, args: Mapping[str, Any]) -> str:
        try:
            days = max(1, min(MAX_DAYS, int(args.get("days") or DEFAULT_DAYS)))
        except (TypeError, ValueError):
            days = DEFAULT_DAYS
        start = today - timedelta(days=days - 1)
        lines = build(
            today, days,
            illness=(await _safely("illness", illness(start)) if illness else None) or (),
            memory=memory,
            pains=(await _safely("pain", pains(start)) if pains else None) or (),
            workouts=(await _safely("workouts", workouts(start)) if workouts else None) or (),
            changes=(await _safely("coach", changes()) if changes else None) or (),
        )  # fmt: skip
        _log.info("timeline: days=%d lines=%d", days, len(lines))
        if not lines:
            return f"最近 {days} 天没有记下什么事。"
        return f"最近 {days} 天（按日期，新的在后）：\n" + "\n".join(lines)

    return run
