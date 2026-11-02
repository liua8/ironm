"""读懂指标趋势（spec [2026-10-23] §84、§85）：每个指标和他自己比、也和标准比；认出是哪种情况，
列出同期发生的、可能有关的事。这里只算事实，不决定怎么调——调不调、调什么由管家复盘里的模型决定（§85）。

每条都带依据：用到的他的数据、计算和资料编号（依据库 K..）；回答正文里不显示，追问时讲得出来。
只说"同时发生、可能有关"，不说成因果，不诊断。阈值写明出处，没有出处的标〔经验〕，待审定。
"""

from __future__ import annotations

import statistics
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from ironm_agent.metrics import (
    Metric,
    Point,
    Profile,
    Readings,
    blood_pressure,
    bmi,
    hrv,
    resting_hr,
    steps,
    week_text,
    weight_trend,
)
from ironm_agent.training import WorkoutLog

type Tone = Literal["good", "attention", "neutral"]
type Kind = Literal["recovery", "sleep", "activity", "fast_loss", "fast_gain", "thin"]

WEEK = 7
BEFORE = 21  # 和前三周比
SLEEP_ENOUGH = 7.0  # 小时（K07）
SLEEP_MIN_NIGHTS = 4  # 最近一周至少这么多晚的记录才判断睡得少
LOAD_UP = 1.3  # 这周练的次数比前三周的周平均多三成以上算突然变多〔经验〕
STEPS_DROP = 0.8  # 这周步数不到前三周平均的八成算掉了〔经验〕
STEPS_FLOOR = 3000  # 前三周平均太少的不判断〔经验〕


@dataclass(frozen=True)
class Reading:
    """一个指标的两种比较。"""

    key: str
    name: str
    mine: str  # 和他自己比
    standard: str  # 和标准比（没有公认标准时说明）
    refs: tuple[str, ...] = ()
    tone: Tone = "neutral"

    def line(self) -> str:
        return f"{self.name}：和你自己比，{self.mine}；和标准比，{self.standard}"


@dataclass(frozen=True)
class Situation:
    """认出的一种情况、同期可能有关的原因和调整。"""

    kind: Kind
    title: str  # 恢复不够
    seen: str  # 看到了什么（带数）
    reasons: tuple[str, ...] = ()  # 同期发生的、可能有关的
    refs: tuple[str, ...] = ()
    data: str = ""

    @property
    def key(self) -> str:
        return f"insight:{self.kind}"

    def line(self) -> str:
        why = f"；同期发生的：{'；'.join(self.reasons)}" if self.reasons else ""
        return f"{self.title}（{self.seen}{why}）"

    def detail(self) -> str:
        """追问依据时讲得出来：看到了什么、同期发生的、用了哪些数据和资料。"""
        parts = [self.line()]
        if self.data:
            parts.append(f"数据：{self.data}")
        if self.refs:
            parts.append(f"依据：{'、'.join(self.refs)}")
        return "。".join(parts)


# ---- 小工具 ---------------------------------------------------------------------------------


def _days(points: Sequence[Point], start: date, end: date) -> list[float]:
    return [v for d, v in points if start <= d <= end]


def _avg(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _week_and_before(points: Sequence[Point], today: date) -> tuple[list[float], list[float]]:
    week = _days(points, today - timedelta(days=WEEK - 1), today)
    before = _days(points, today - timedelta(days=WEEK + BEFORE - 1), today - timedelta(days=WEEK))
    return week, before


def _f(x: float, places: int = 1) -> str:
    return f"{x:.{places}f}".rstrip("0").rstrip(".") if places else str(round(x))


def _flag(m: Metric, words: Collection[str]) -> bool:
    return m.ok and m.brief in words


# ---- 两种比较 -------------------------------------------------------------------------------


def compare(readings: Readings, profile: Profile, today: date) -> list[Reading]:
    """有数据的指标，各自和他自己比、和标准比。"""
    out: list[Reading] = []
    age = profile.age(today)
    rhr = resting_hr(readings.resting_hr, today)
    if rhr.ok and rhr.value is not None:
        v = rhr.value
        std = (
            "高于 100 次/分，超过了成年人的正常范围，持续这样要看医生"
            if v > 100
            else "低于 60 次/分；常运动的人可以更低，没有头晕乏力就不用担心"
            if v < 60
            else "在成年人正常范围（60–100 次/分）内"
        )
        out.append(Reading("resting_hr", "静息心率", rhr.text, std, ("K18", "K20"),
                           "attention" if v > 100 or rhr.tone == "attention" else "good"))  # fmt: skip
    for algo, pts in (("SDNN", readings.hrv_sdnn), ("RMSSD", readings.hrv_rmssd)):
        m = hrv(pts, algo, today)
        if m.ok:
            out.append(Reading(m.key, m.name, m.text,
                               "心率变异性没有公认的人群标准，个人差异很大，只和你自己比",
                               ("K18", "K19"), m.tone))  # fmt: skip
    week, before = _week_and_before(readings.sleep_hours, today)
    if week:
        avg, prev = statistics.fmean(week), _avg(before)
        mine = week_text(len(week), _f(avg), "小时", nights=True) + (
            f"，前三周平均 {_f(prev)} 小时" if prev is not None else "，还没有前几周的记录可比"
        )
        std = (
            f"达到成年人每晚 {_f(SLEEP_ENOUGH)} 小时的建议"
            if avg >= SLEEP_ENOUGH
            else f"低于成年人每晚 {_f(SLEEP_ENOUGH)} 小时的建议"
        )
        out.append(Reading("sleep", "睡眠时长", mine, std, ("K07",),
                           "good" if avg >= SLEEP_ENOUGH else "attention"))  # fmt: skip
    week, before = _week_and_before(readings.steps, today)
    if week:
        avg, prev = statistics.fmean(week), _avg(before)
        mine = week_text(len(week), str(round(avg)), "步") + (
            f"，前三周平均 {round(prev)} 步" if prev is not None else ""
        )
        m = steps(readings.steps, age, today)
        lo = 6000 if age is not None and age >= 60 else 8000
        std = (
            f"{'达到' if avg >= lo else '低于'}{'60 岁以上' if lo == 6000 else '成年人'}"
            f"每天 {lo} 步左右（多走收益趋于平稳的起点）"
        )
        out.append(Reading("steps", "步数", mine, std, ("K21",), m.tone))
    sys_pt = max(readings.systolic, default=None)
    dia_pt = max(readings.diastolic, default=None)
    if sys_pt is not None and dia_pt is not None:
        bp = blood_pressure(sys_pt, dia_pt)
        week_s, before_s = _week_and_before(readings.systolic, today)
        mine = (
            f"最近 7 天收缩压平均 {round(statistics.fmean(week_s))}，前三周平均 {round(statistics.fmean(before_s))}"
            if week_s and before_s
            else "记录还不够，暂不和前几周比"
        )
        out.append(Reading("blood_pressure", "血压", mine, bp.text, ("K41",), bp.tone))
    if readings.weight:
        trend = weight_trend(readings.weight, today)
        latest = max(readings.weight)
        b = bmi(latest, profile.height_cm or readings.height_cm)
        mine = trend.text if trend.ok else "称重还不够，暂不判断每周变化"
        std = b.text if b.ok else "缺身高，算不出 BMI"
        rate = _rate(trend, latest[1], profile.goal)
        if rate:
            std += f"；{rate}"
        out.append(Reading("weight", "体重", mine, std, ("K16", "K37", "K88"), b.tone))
    return out


def _rate(trend: Metric, weight: float, goal: str | None) -> str:
    """体重每周变化和这个目标的合理速度比（减脂每周 0.5–1%，增肌每周 0.25–0.5%）。"""
    if not trend.ok or trend.value is None or not weight:
        return ""
    pct = trend.value / weight * 100
    if goal == "fat_loss":
        word = "偏快" if pct < -1 else "在合理范围" if pct <= -0.5 else "偏慢或没在降"
        return f"每周 {pct:+.1f}%，减脂每周减体重的 0.5–1% 比较合理，{word}"
    if goal == "muscle":
        word = "偏快" if pct > 0.5 else "在合理范围" if pct >= 0.25 else "偏慢"
        return f"每周 {pct:+.1f}%，增肌每周涨体重的 0.25–0.5% 比较合理，{word}"
    return ""


# ---- 认出情况、找原因、给调整 -------------------------------------------------------------------


def situations(
    readings: Readings,
    profile: Profile,
    today: date,
    *,
    logs: Sequence[WorkoutLog] = (),
    illness: Sequence[str] = (),
    events: Sequence[str] = (),
) -> list[Situation]:
    """认出的情况。illness：正在生病的说法（"昨天说感冒"）；events：近期事件（出差等）。"""
    out: list[Situation] = []
    rhr, sdnn, rmssd = (resting_hr(readings.resting_hr, today), hrv(readings.hrv_sdnn, "SDNN", today),
                        hrv(readings.hrv_rmssd, "RMSSD", today))  # fmt: skip
    high = _flag(rhr, ("明显偏高",))
    low = _flag(sdnn, ("明显偏低",)) or _flag(rmssd, ("明显偏低",))
    nights, _ = _week_and_before(readings.sleep_hours, today)
    slept = _avg(nights) if len(nights) >= SLEEP_MIN_NIGHTS else None
    short = slept is not None and slept < SLEEP_ENOUGH
    done = [x for x in logs if x.done]
    this_week = sum(1 for x in done if today - timedelta(days=WEEK - 1) <= x.day <= today)
    earlier = sum(
        1
        for x in done
        if today - timedelta(days=WEEK + BEFORE - 1) <= x.day < today - timedelta(days=WEEK - 1)
    )
    per_week = earlier / (BEFORE / WEEK)
    load_up = per_week > 0 and this_week >= per_week * LOAD_UP and this_week - per_week >= 1

    reasons: list[str] = []
    if short and slept is not None:
        few = "" if len(nights) >= WEEK else f"有 {len(nights)} 晚记录，"
        reasons.append(f"最近 7 天{few}平均只睡 {_f(slept)} 小时，不到 {_f(SLEEP_ENOUGH)} 小时")
    if load_up:
        reasons.append(f"这周练了 {this_week} 次，前三周平均每周 {_f(per_week)} 次")
    reasons += list(illness) + [f"近期：{e}" for e in events]

    # 恢复不够：身体信号偏离平常，再加上同期有能解释的原因，或两个信号同时偏离
    if (high or low) and (reasons or (high and low)):
        hrv_pts = readings.hrv_sdnn if _flag(sdnn, ("明显偏低",)) else readings.hrv_rmssd
        seen = "；".join(
            x for x in (_usual("静息心率", readings.resting_hr, "高", 0) if high else "",
                        _usual("心率变异性", hrv_pts, "低", 0) if low else "") if x
        )  # fmt: skip
        out.append(Situation(
            "recovery", "恢复不够", seen, tuple(reasons),
            refs=("K18", "K81", "K82", "K31"),
            data="最近 7 天和之前的静息心率、心率变异性、睡眠；最近 4 周的训练记录",
        ))  # fmt: skip
    if short and slept is not None:
        out.append(Situation(
            "sleep", "睡得少", f"{week_text(len(nights), _f(slept), '小时', nights=True)}，成年人建议每晚 {_f(SLEEP_ENOUGH)} 小时以上", refs=("K07", "K34", "K113"),
            data=f"最近 7 天的睡眠记录 {len(nights)} 晚",
        ))  # fmt: skip
    week, before = _week_and_before(readings.steps, today)
    prev = _avg(before)
    if (
        week
        and prev is not None
        and prev >= STEPS_FLOOR
        and statistics.fmean(week) < prev * STEPS_DROP
    ):
        now = statistics.fmean(week)
        why = tuple([*illness, *(f"近期：{e}" for e in events)])
        out.append(Situation(
            "activity", "活动量掉了", f"最近 7 天平均 {round(now)} 步，前三周平均 {round(prev)} 步", why,
            refs=("K21", "K64"), data=f"最近 4 周的步数记录 {len(week) + len(before)} 天",
        ))  # fmt: skip
    trend = weight_trend(readings.weight, today)
    if trend.ok and trend.value is not None and readings.weight:
        weight = max(readings.weight)[1]
        pct = trend.value / weight * 100
        if profile.goal == "fat_loss" and pct < -1:
            out.append(Situation(
                "fast_loss", "减得太快", f"体重每周 {pct:+.1f}%，减脂每周 0.5–1% 比较合理", refs=("K37", "K87", "K16"),
                data=trend.data,
            ))  # fmt: skip
        if profile.goal == "muscle" and pct > 0.5:
            out.append(Situation(
                "fast_gain", "增重太快", f"体重每周 {pct:+.1f}%，增肌每周 0.25–0.5% 比较合理", refs=("K88", "K89"),
                data=trend.data,
            ))  # fmt: skip
    if not any((readings.resting_hr, readings.hrv_sdnn, readings.hrv_rmssd, readings.sleep_hours,
                readings.steps, readings.weight)):  # fmt: skip
        out.append(Situation("thin", "数据不够", "还没有心率、睡眠、步数、体重的记录",))  # fmt: skip
    return out


def _usual(name: str, points: Sequence[Point], word: str, places: int) -> str:
    """ "静息心率这周平均 66，比平常（58）高"：平常是之前最多 60 天的平均（和数据页同样的取法）。"""
    end = max(d for d, _ in points)
    week = _days(points, end - timedelta(days=WEEK - 1), end)
    usual = _days(points, end - timedelta(days=WEEK + 60 - 1), end - timedelta(days=WEEK))
    if not week or not usual:
        return ""
    return f"{name}这周平均 {_f(statistics.fmean(week), places)}，比平常（{_f(statistics.fmean(usual), places)}）{word}"
