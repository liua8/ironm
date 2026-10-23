"""训练规律汇总：最近一段时间练了几次、常在周几、每次多久、感受、按计划的完成率、常练和常跳过的动作。

只算事实；"他偏好什么"由角色或后台的偏好提取来判断。
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Sequence
from datetime import date, timedelta

from ironm_agent.protools.result import Finding, Result
from ironm_agent.training import Plan, WorkoutLog, weekday_name

WINDOWS = (14, 28, 56)
MIN_SESSIONS = 6  # 至少 6 次训练
MIN_SPAN_DAYS = 14  # 跨 2 周以上
SKIP_SHARE = 0.5  # 按计划该练的次数里记下来不到一半，算常跳过


def _planned_days(plan: Plan, start: date, today: date) -> list[date]:
    days = {s.day for s in plan.sessions}
    out, d = [], start
    while d <= today:
        if d.isoweekday() in days:
            out.append(d)
        d += timedelta(days=1)
    return out


def training_patterns(
    logs: Sequence[WorkoutLog],
    today: date,
    *,
    days: int = 28,
    plan: Plan | None = None,
    plan_since: date | None = None,
) -> Result:
    if days not in WINDOWS:
        days = min(WINDOWS, key=lambda w: abs(w - days))
    start = today - timedelta(days=days - 1)
    window = sorted((x for x in logs if start <= x.day <= today), key=lambda x: x.day)
    done = [x for x in window if x.done]
    span = (today - done[0].day).days + 1 if done else 0
    data = f"{start.isoformat()} 到 {today.isoformat()} 的训练记录 {len(window)} 条"
    if len(done) < MIN_SESSIONS or span < MIN_SPAN_DAYS:
        lack = []
        if len(done) < MIN_SESSIONS:
            lack.append(f"还差 {MIN_SESSIONS - len(done)} 次")
        if span < MIN_SPAN_DAYS:
            lack.append(f"记录还不满 {MIN_SPAN_DAYS} 天")
        return Result(
            (
                Finding(
                    "训练规律",
                    f"最近 {days} 天完成了 {len(done)} 次训练，数据不足，看不出规律（{'，'.join(lack)}）",
                    f"至少要 {MIN_SESSIONS} 次训练、跨 {MIN_SPAN_DAYS} 天以上才汇总规律",
                    data,
                ),
            )
        )
    findings: list[Finding] = []
    per_week = len(done) / (days / 7)
    weekdays = Counter(x.day.isoweekday() for x in done)
    top = "、".join(f"{weekday_name(d)} {n} 次" for d, n in weekdays.most_common(3))
    parts = [f"最近 {days} 天完成 {len(done)} 次，平均每周 {per_week:.1f} 次", f"常在{top}"]
    minutes = [x.minutes for x in done if x.minutes]
    if minutes:
        parts.append(
            f"每次平均 {statistics.fmean(minutes):.0f} 分钟（{min(minutes)}–{max(minutes)}）"
        )
    rpes = [x.rpe for x in done if x.rpe]
    if rpes:
        hard = sum(1 for r in rpes if r >= 8)
        parts.append(f"感受平均 {statistics.fmean(rpes):.1f} 分，8 分及以上 {hard} 次")
    missed = len(window) - len(done)
    if missed:
        parts.append(f"另有 {missed} 次没练完")
    findings.append(
        Finding(
            "训练规律",
            "；".join(parts),
            f"在 {days} 天里按日期统计完成的训练：次数 ÷ {days / 7:g} 周得每周平均；周几取次数最多的 3 天；"
            "时长和感受只算记了的那几次",
            data,
        )
    )
    if plan is not None:
        begin = max(start, plan_since) if plan_since else start
        planned = _planned_days(plan, begin, today)
        if planned:
            done_days = {x.day for x in done}
            hit = sum(1 for d in planned if d in done_days)
            findings.append(
                Finding(
                    "按计划的完成率",
                    f"{begin.isoformat()} 起按计划该练 {len(planned)} 次，当天练了 {hit} 次，完成率 {hit / len(planned) * 100:.0f}%",
                    "按计划里每周练的那几天数出该练的日子，看当天有没有完成的记录",
                    f"当前计划《{plan.title}》与{data}",
                )
            )
    named = [it.exercise for x in done for it in x.items]
    if named:
        common = Counter(named).most_common(3)
        findings.append(
            Finding(
                "常练的动作",
                "、".join(f"{n} {c} 次" for n, c in common),
                "数训练记录里每个动作出现的次数",
                data,
            )
        )
        if plan is not None:
            logged = Counter(named)
            sessions_with_items = sum(1 for x in done if x.items)
            want = Counter(it.exercise for s in plan.sessions for it in s.items)
            weeks = days / 7
            skipped = [
                f"{name}（计划每周 {per} 次，记录 {logged.get(name, 0)} 次）"
                for name, per in want.items()
                if per * weeks >= 2 and logged.get(name, 0) < per * weeks * SKIP_SHARE
            ]
            if skipped and sessions_with_items >= MIN_SESSIONS // 2:
                findings.append(
                    Finding(
                        "常跳过的动作",
                        "、".join(skipped),
                        f"计划里的动作，记录次数不到按计划该做次数的 {SKIP_SHARE * 100:.0f}%",
                        f"当前计划与{data}（只算写了动作的记录）",
                    )
                )
    return Result(tuple(findings))
