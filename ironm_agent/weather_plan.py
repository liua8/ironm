"""天气是训练安排的一部分（spec [2026-10-23] §34）：按本周每天的天气，规则改出那天的训练版本。

- 那天的计划里有户外动作（跑步、骑车、快走等），天气不适合户外（建议室内或避免户外）：户外动作换成室内的；
  同一周里以后还有天气好的休息日，再建议"也可以挪到那天"。
- 高温到 35℃（预警黄色档）还不到改室内的程度：提醒降低强度、避开中午、多补水。
- 今天用实时天气的判断（含空气质量），以后几天用预报；过去的日子不调整。原计划不变，只是那天的版本。
不调用模型；管家方案、首页本周计划、对话的共享档案都用这一份。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from ironm_agent.today import INDOOR, build, is_outdoor
from ironm_agent.training import Plan, Session
from ironm_agent.weather import HEAT, Advice, Day, assess_day

BAD = ("indoor", "avoid")
HOT = min(t for t, lv in HEAT if lv == "caution")  # 35℃


@dataclass(frozen=True)
class DayPlan:
    day: date
    session: Session | None
    weather: Day | None = None  # 预报（今天没有预报时为空）
    advice: Advice | None = None  # 天气对训练的影响（今天用实时天气）
    version: Session | None = None  # 按天气改出的版本；没改时为空
    changes: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    better: date | None = None  # 同一周以后天气好的休息日，可以挪过去
    outdoor: tuple[str, ...] = field(default_factory=tuple)  # 计划里的户外动作

    @property
    def adjusted(self) -> bool:
        return bool(self.changes)


def _hot(d: Day | None) -> bool:
    return d is not None and d.tmax >= HOT


def _free_good(
    y: date, plan: Plan | None, advice: dict[date, Advice | None], forecast: dict[date, Day | None]
) -> bool:
    """这天没有安排训练、天气适合户外又不热：可以把户外有氧挪过来。"""
    a = advice.get(y)
    return (
        (plan is None or plan.session_on(y) is None)
        and a is not None
        and a.level == "good"
        and not _hot(forecast.get(y))
    )


def week_plan(
    plan: Plan | None,
    days: Sequence[Day],
    today: date,
    now: Advice | None = None,
) -> list[DayPlan]:
    """本周一到周日每天的计划和天气；days 是预报（今天起），now 是今天实时天气的判断。"""
    monday = today - timedelta(days=today.isoweekday() - 1)
    by_day = {d.day: d for d in days}
    out: list[DayPlan] = []
    week = [monday + timedelta(days=i) for i in range(7)]
    forecast = {x: by_day.get(x.isoformat()) for x in week}
    advice = {x: (now if x == today and now is not None else (assess_day(f) if f else None)) for x, f in forecast.items()}  # fmt: skip
    for x in week:
        session = plan.session_on(x) if plan else None
        f, adv = forecast[x], advice[x]
        outdoor = (
            tuple(i.exercise for i in session.items if is_outdoor(i.exercise)) if session else ()
        )
        if session is None or x < today or adv is None:
            out.append(DayPlan(x, session, f, adv, outdoor=outdoor))
            continue
        changes: list[str] = []
        reasons: list[str] = []
        version = None
        better = None
        if adv.level in BAD and outdoor:
            v = build(
                session, indoor=True, indoor_why=adv.reasons[0] if adv.reasons else "天气不宜户外"
            )
            version, changes, reasons = v.session, list(v.changes), list(v.reasons)
            better = next(
                (y for y in week if y > x and _free_good(y, plan, advice, forecast)), None
            )
        elif _hot(f) and adv.level not in BAD:
            changes.append("降低强度、缩短时间，避开中午，多补水")
            reasons.append(f"最高气温约 {f.tmax:.0f}℃，达到高温预警的 {HOT}℃ 档" if f else "高温")
        out.append(
            DayPlan(x, session, f, adv, version, tuple(changes), tuple(reasons), better, outdoor)
        )
    return out


WEEKDAYS = "一二三四五六日"


def weekday(d: date) -> str:
    return f"周{WEEKDAYS[d.isoweekday() - 1]}"


def line(p: DayPlan) -> str:
    """一天的调整写成一句话（管家方案和共享档案用）。"""
    text = p.weather.text if p.weather else ""
    head = f"{weekday(p.day)}{text}" if text else weekday(p.day)
    body = "；".join(p.changes)
    tail = f"，也可以挪到{weekday(p.better)}（天气好）" if p.better else ""
    return f"{head}：{p.session.name if p.session else ''}{body and '，' + body}{tail}"


def forecast_line(days: Sequence[Day], today: date, n: int = 6) -> str:
    """未来几天的天气，写进共享档案（训练教练排计划、安排今天时照顾天气）。"""
    parts: list[str] = []
    for d in days:
        x = date.fromisoformat(d.day)
        if x <= today or len(parts) >= n:
            continue
        rain = f"，降水{d.rain}%" if d.rain is not None and d.rain >= 30 else ""
        parts.append(f"{weekday(x)}{d.text} {d.tmin:.0f}–{d.tmax:.0f}℃{rain}")
    return "；".join(parts)


__all__ = ["INDOOR", "DayPlan", "forecast_line", "line", "week_plan", "weekday"]
