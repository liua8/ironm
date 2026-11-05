"""打卡分享卡和周报（spec [2026-11-03] §147）：只用训练、饮食、指标记录按规则算，不调用模型。"""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from datetime import date, timedelta
from typing import Any

from ironm_agent.training import LogItem, WorkoutLog, week_of

DIET_BAND = 0.10  # 饮食达标：一天吃的在目标热量上下 10% 以内


def _reps(text: str) -> int:
    m = re.match(r"\d+", text.strip())
    return int(m.group()) if m else 0


def done_sets(it: LogItem) -> list[tuple[float, int]]:
    """这个动作做了的组（重量、次数），只算记了重量的；没逐组记的按计划组数和次数算。"""
    if it.done_sets:
        return [(s.weight_kg, s.reps) for s in it.done_sets if s.weight_kg and s.reps]
    if it.weight_kg and _reps(it.reps):
        return [(it.weight_kg, _reps(it.reps))] * (it.sets or 1)
    return []


def set_count(log: WorkoutLog) -> int:
    return sum(len(it.done_sets) or it.sets or 0 for it in log.items)


def volume(log: WorkoutLog) -> float:
    """总重量：每组重量×次数相加（公斤）。"""
    return round(sum(w * r for it in log.items for w, r in done_sets(it)), 1)


def best(it: LogItem) -> tuple[float, int] | None:
    """这个动作最好的一组：重的优先，一样重次数多的优先（和战绩页的成就同一个比法）。"""
    sets = done_sets(it)
    return max(sets) if sets else None


def records(log: WorkoutLog, earlier: Sequence[WorkoutLog]) -> list[dict[str, Any]]:
    """这次破的纪录：这个动作这次最好的一组比以前每一次都好；以前没做过的不算破纪录。"""
    before: dict[str, tuple[float, int]] = {}
    for x in earlier:
        if not x.done or x.day >= log.day:
            continue
        for it in x.items:
            b = best(it)
            if b is not None and (it.exercise not in before or b > before[it.exercise]):
                before[it.exercise] = b
    out = []
    for it in log.items:
        b = best(it)
        if b is not None and it.exercise in before and b > before[it.exercise]:
            out.append({"exercise": it.exercise, "weight_kg": b[0], "reps": b[1]})
    return out


def workout_card(
    log: WorkoutLog, history: Sequence[WorkoutLog], streak_days: int
) -> dict[str, Any]:
    """分享卡上的数：哪天、练的什么、时长、组数、总重量、破的纪录、连续打卡天数。不放身体数据。"""
    return {
        "day": log.day.isoformat(),
        "session": log.session or "训练",
        "minutes": log.minutes,
        "sets": set_count(log),
        "volume_kg": volume(log),
        "moves": [it.exercise for it in log.items],
        "records": records(log, history),
        "streak_days": streak_days,
        "rpe": log.rpe,
    }


def _weight_change(weights: Sequence[tuple[date, float]], monday: date) -> dict[str, float] | None:
    got = sorted((d, w) for d, w in weights if monday <= d <= monday + timedelta(days=6))
    if len(got) < 2:
        return None
    return {"from": got[0][1], "to": got[-1][1], "change": round(got[-1][1] - got[0][1], 1)}


def _diet(day_kcal: dict[date, float], target: float | None, monday: date) -> dict[str, int] | None:
    days = [day_kcal[d] for d in (monday + timedelta(days=i) for i in range(7)) if d in day_kcal]
    if not days or not target:
        return None
    hit = sum(abs(k - target) <= target * DIET_BAND for k in days)
    return {"logged": len(days), "on_target": hit}


def week_report(
    monday: date,
    plan: Any,
    since: date | None,
    logs: Sequence[WorkoutLog],
    *,
    weights: Sequence[tuple[date, float]] = (),
    day_kcal: dict[date, float] | None = None,
    kcal_target: float | None = None,
    tips: Sequence[str] = (),
    sick: Collection[date] = (),
) -> dict[str, Any]:
    """那一周（monday 起七天）的周报。logs 要包括那周之前的记录（算破纪录用）。没记录的项为 None。"""
    sunday = monday + timedelta(days=6)
    mine = [x for x in logs if x.done and monday <= x.day <= sunday]
    planned = week_of(plan, logs, sunday, since, sick).planned if plan is not None else None
    found: dict[str, dict[str, Any]] = {}
    for x in sorted(mine, key=lambda r: r.day):
        for r in records(x, logs):
            found[r["exercise"]] = r  # 一周里同一个动作破了几次，留最后（最好）的那次
    rpes = [x.rpe for x in mine if x.rpe]
    return {
        "from": monday.isoformat(),
        "to": sunday.isoformat(),
        "done": len({x.day for x in mine}),
        "planned": planned,
        "minutes": sum(x.minutes or 0 for x in mine),
        "sets": sum(set_count(x) for x in mine),
        "volume_kg": round(sum(volume(x) for x in mine), 1),
        "records": list(found.values()),
        "weight": _weight_change(weights, monday),
        "diet": _diet(day_kcal or {}, kcal_target, monday),
        "rpe": round(sum(rpes) / len(rpes), 1) if rpes else None,
        "focus": tips[0] if tips else "照计划来，保持节奏。",
    }
