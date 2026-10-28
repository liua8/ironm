"""首页战报：本周、本月的统计（spec [2026-10-23] §64）。只用规则，不调用模型。"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import date, timedelta
from typing import Any, Literal

from ironm_agent.training import StoredPlan, WorkoutLog, week_of, week_start

STREAK_WEEKS = 52  # 连续达标最多往前数几周


def month_days(first: date) -> list[date]:
    nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return [first + timedelta(days=i) for i in range((nxt - first).days)]


def plan_on(versions: Sequence[StoredPlan], day: date) -> StoredPlan | None:
    """那天在用的那版计划：启用日期不晚于那天的最后一版（versions 按启用先后排）。"""
    current = None
    for v in versions:
        if v.since <= day:
            current = v
    return current


def planned_days(
    versions: Sequence[StoredPlan], first: date, sick: Collection[date] = ()
) -> int | None:
    """本月应练几天：每天按那天在用的计划，排了训练就算；没计划、生病的日子不算。整月都没计划时为 None。"""
    count, covered = 0, False
    for day in month_days(first):
        v = plan_on(versions, day)
        if v is None:
            continue
        covered = True
        if day not in sick and any(s.day == day.isoweekday() for s in v.plan.sessions):
            count += 1
    return count if covered else None


def _week(
    versions: Sequence[StoredPlan],
    logs: Sequence[WorkoutLog],
    monday: date,
    today: date,
    sick: Collection[date],
) -> Literal["hit", "miss", "skip", "stop"]:
    """这一周：达标、没达标、整周生病（计划次数为 0，跳过）、没有计划（停下）。"""
    end = min(monday + timedelta(days=6), today)
    v = plan_on(versions, end)
    if v is None:
        return "stop"
    w = week_of(v.plan, logs, end, v.since, sick)
    if w.planned == 0:
        return "skip"
    return "hit" if w.done >= w.planned else "miss"


def streak(
    versions: Sequence[StoredPlan],
    logs: Sequence[WorkoutLog],
    last: date,
    today: date,
    sick: Collection[date] = (),
) -> int:
    """连续达标几周：从 last 所在的那周往前数；本周还没达标就从上周数起；整周生病的跳过，没计划的停下。"""
    monday = week_start(min(last, today))
    n = 0
    for k in range(STREAK_WEEKS):
        wk = monday - timedelta(weeks=k)
        got = _week(versions, logs, wk, today, sick)
        if got == "stop" or (got == "miss" and wk != week_start(today)):
            break  # 本周还没练够不算断
        n += got == "hit"
    return n


def done_days(logs: Sequence[WorkoutLog]) -> set[date]:
    return {x.day for x in logs if x.done}


def versus_last_month(done: Collection[date], first: date, today: date) -> tuple[int, str]:
    """和上个月比多练了几天：当前月份比上月同期（1 日到今天这个日子），以前的月份比整月。"""
    prev = (first - timedelta(days=1)).replace(day=1)
    this_days, prev_days = month_days(first), month_days(prev)
    if first == today.replace(day=1):
        this_days = this_days[: today.day]
        prev_days = prev_days[: today.day]
        label = "比上月同期"
    else:
        label = "比上个月"
    return sum(d in done for d in this_days) - sum(d in done for d in prev_days), label


def week_rpe(logs: Sequence[WorkoutLog], today: date) -> float | None:
    """本周打卡里填了感受分的平均，一位小数；都没填为 None。"""
    start = week_start(today)
    got = [x.rpe for x in logs if x.done and x.rpe and start <= x.day <= today]
    return round(sum(got) / len(got), 1) if got else None


def report(
    versions: Sequence[StoredPlan],
    logs: Sequence[WorkoutLog],
    first: date,
    today: date,
    sick: Collection[date] = (),
) -> dict[str, Any]:
    """这个月的战报统计和本周的平均感受分。logs 要从 first 往前至少 STREAK_WEEKS 周、上个月 1 日起。"""
    done = done_days(logs)
    last = month_days(first)[-1]
    diff, label = versus_last_month(done, first, today)
    return {
        "month_stats": {
            "done_days": sum(d in done for d in month_days(first)),
            "planned_days": planned_days(versions, first, sick),
            "streak_weeks": streak(versions, logs, last, today, sick),
            "versus": diff,
            "versus_label": label,
        },
        "week": {"rpe": week_rpe(logs, today)},
    }


def history_start(first: date) -> date:
    """战报要读多早的训练记录：连续达标往前数的周数，加上上个月。"""
    last = month_days(first)[-1]
    return min(
        week_start(last) - timedelta(weeks=STREAK_WEEKS), (first - timedelta(days=1)).replace(day=1)
    )
