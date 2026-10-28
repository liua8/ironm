"""首页战报的本月、本周统计（spec [2026-10-23] §64）。"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from ironm_agent.report import planned_days, streak, versus_last_month, week_rpe
from ironm_agent.training import Plan, StoredPlan, WorkoutLog

TODAY = date(2026, 10, 28)  # 周三
OCT = date(2026, 10, 1)


def plan(*weekdays: int) -> Plan:
    return Plan.model_validate(
        {
            "title": "测试",
            "days_per_week": len(weekdays),
            "sessions": [
                {
                    "day": d,
                    "name": f"第{d}天",
                    "items": [{"exercise": "深蹲", "sets": 3, "reps": "10"}],
                }
                for d in weekdays
            ],
        }
    )


def version(since: date, *weekdays: int) -> StoredPlan:
    return StoredPlan(
        since.isoformat(), plan(*weekdays), datetime.combine(since, time(12)).astimezone()
    )


def done(*days: date, rpe: int | None = None) -> list[WorkoutLog]:
    return [WorkoutLog(day=d, rpe=rpe) for d in days]


def week_days(monday: date, *offsets: int) -> list[date]:
    return [monday + timedelta(days=k) for k in offsets]


def test_planned_days_follow_each_version() -> None:
    v1, v2 = version(OCT, 1, 3, 5), version(date(2026, 10, 15), 2, 4)
    # 1–14 日按一三五：2、5、7、9、12、14；15 日起按二四：15、20、22、27、29
    assert planned_days([v1, v2], OCT) == 11
    assert planned_days([v1, v2], OCT, sick={date(2026, 10, 20), date(2026, 10, 21)}) == 10
    # 第一份计划 8 日才开始：之前的日子不算
    assert planned_days([version(date(2026, 10, 8), 1, 3, 5)], OCT) == 10
    assert planned_days([], OCT) is None
    assert planned_days([version(date(2026, 11, 2), 1)], OCT) is None


MON = [date(2026, 9, 21) + timedelta(weeks=k) for k in range(6)]  # 9-21 … 10-26 各周的周一


def test_streak_counts_back_and_skips_unfinished_current_week() -> None:
    v = [version(date(2026, 9, 1), 1, 3, 5)]
    logs = done(
        *week_days(MON[1], 0, 2, 4),  # 9-28 周达标
        *week_days(MON[2], 0, 2),  # 10-5 周只练了两次
        *week_days(MON[3], 0, 2, 4),
        *week_days(MON[4], 1, 3, 5),  # 不在计划那天练也算次数
        MON[5],  # 本周到今天只练了一次
    )
    assert streak(v, logs, date(2026, 10, 31), TODAY) == 2
    more = logs + done(MON[5] + timedelta(days=1), MON[5] + timedelta(days=2))
    assert streak(v, more, date(2026, 10, 31), TODAY) == 3  # 本周已经达标就算上
    assert streak(v, logs, date(2026, 9, 30), TODAY) == 1  # 9 月：从 9-28 那周往前数


def test_streak_skips_sick_weeks_and_stops_without_plan() -> None:
    logs = done(
        *week_days(MON[1], 0, 2, 4), *week_days(MON[3], 0, 2, 4), *week_days(MON[4], 0, 2, 4)
    )
    sick = set(week_days(MON[2], 0, 1, 2, 3, 4, 5, 6))  # 10-5 那周整周生病
    v = [version(date(2026, 9, 1), 1, 3, 5)]
    assert streak(v, logs, date(2026, 10, 31), TODAY, sick) == 3
    assert streak(v, logs, date(2026, 10, 31), TODAY) == 2  # 不算生病：那周没练就断了
    late = [version(MON[3], 1, 3, 5)]  # 10-12 才有计划
    assert streak(late, logs, date(2026, 10, 31), TODAY) == 2


def test_versus_last_month() -> None:
    days = {date(2026, 9, 3), date(2026, 9, 29), date(2026, 10, 1), date(2026, 10, 2)}
    assert versus_last_month(days, OCT, TODAY) == (1, "比上月同期")  # 9-29 在同期之后，不算
    assert versus_last_month(days, date(2026, 9, 1), TODAY) == (2, "比上个月")
    assert versus_last_month(set(), OCT, TODAY) == (0, "比上月同期")


def test_week_rpe() -> None:
    logs = [
        *done(MON[5], rpe=6),
        *done(MON[5] + timedelta(days=1), rpe=9),
        WorkoutLog(day=MON[5] + timedelta(days=1), done=False, rpe=3),  # 没练完的不算
        *done(MON[5] - timedelta(days=1), rpe=10),  # 上周日不算
        *done(MON[5] + timedelta(days=2)),  # 没填感受分
    ]
    assert week_rpe(logs, TODAY) == 7.5
    assert week_rpe(done(MON[5]), TODAY) is None
