"""读懂指标趋势（spec [2026-10-23] §84、§85）：每个指标和他自己比、也和标准比；列出最近 7 天和之前比的变化，
和同期发生的事（练的次数、生病、出差）。这里只算事实，不贴"恢复不够、睡得少"这类标签（§182 需求 7），
也不决定怎么调——调不调、调什么由管家复盘里的模型决定（§85）。

每条都带依据：用到的他的数据、计算和资料编号（依据库 K..）；回答正文里不显示，追问时讲得出来。
只说"同时发生、可能有关"，不说成因果，不诊断。阈值写明出处，没有出处的标〔经验〕，待审定。
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
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
type Kind = Literal[
    "resting_hr",
    "hrv_sdnn",
    "hrv_rmssd",
    "sleep",
    "steps",
    "weight",
    "training",
    "illness",
    "event",
    "thin",
]

WEEK = 7
BEFORE = 21  # 和前三周比
SLEEP_ENOUGH = 7.0  # 小时（K07）
USUAL = 60  # "平常"取之前最多 60 天（和数据页同样的取法）
CONTEXT: frozenset[str] = frozenset(
    {"training", "illness", "event"}
)  # 同期发生的事（不是指标本身）


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
class Observation:
    """一条事实：哪个指标、最近和之前各是多少、差多少、哪段时间；或者同期发生的一件事。不下结论（§182）。"""

    kind: Kind
    name: str  # 静息心率
    seen: str  # 看到了什么（带数和时间段）
    refs: tuple[str, ...] = ()
    data: str = ""

    @property
    def key(self) -> str:
        return f"insight:{self.kind}"

    def line(self) -> str:
        return f"{self.name}：{self.seen}"

    def detail(self) -> str:
        """追问依据时讲得出来：看到了什么、用了哪些数据和资料。"""
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
        return f"每周 {pct:+.1f}%（减脂每周减体重的 0.5–1% 比较合理）"
    if goal == "muscle":
        return f"每周 {pct:+.1f}%（增肌每周涨体重的 0.25–0.5% 比较合理）"
    return ""


# ---- 最近的变化和同期发生的事（只是事实，§182）------------------------------------------------------


def _change(points: Sequence[Point], today: date, unit: str, places: int, *, pct: bool = False,
            usual_days: int = USUAL, usual_name: str = "") -> str:  # fmt: skip
    """ "最近 7 天平均 66 次/分，之前 40 天平均 58 次/分，高 8"：最近 7 天没有记录时为空。"""
    week = _days(points, today - timedelta(days=WEEK - 1), today)
    if not week:
        return ""
    before = _days(
        points, today - timedelta(days=WEEK + usual_days - 1), today - timedelta(days=WEEK)
    )
    now = statistics.fmean(week)
    few = "" if len(week) >= WEEK else f"（有 {len(week)} 天记录）"
    out = f"最近 7 天{few}平均 {_f(now, places)}{unit}"
    if not before:
        return out + "，之前还没有记录可比"
    was = statistics.fmean(before)
    diff = (now - was) / was * 100 if pct and was else now - was
    size = f"{abs(diff):.0f}" if pct else _f(abs(diff), places)
    word = (
        "和之前一样"
        if size == "0"
        else f"{'高' if diff > 0 else '低'} {size}{'%' if pct else unit}"
    )
    return out + f"，{usual_name or f'之前 {len(before)} 天'}平均 {_f(was, places)}{unit}，{word}"


def observations(
    readings: Readings,
    profile: Profile,
    today: date,
    *,
    logs: Sequence[WorkoutLog] = (),
    illness: Sequence[str] = (),
    events: Sequence[str] = (),
) -> list[Observation]:
    """最近 7 天和他自己之前比的变化，和同期发生的事。illness：正在生病的说法（"昨天说感冒"）；
    events：近期事件（出差等）。只列数和差，不判断是不是"恢复不够、睡得少、减得太快"（§182）。"""
    out: list[Observation] = []
    body: tuple[tuple[Kind, str, Sequence[Point], str, bool, tuple[str, ...]], ...] = (
        ("resting_hr", "静息心率", readings.resting_hr, " 次/分", False, ("K18",)),
        ("hrv_sdnn", "心率变异性（SDNN）", readings.hrv_sdnn, " 毫秒", True, ("K18", "K19")),
        ("hrv_rmssd", "心率变异性（RMSSD）", readings.hrv_rmssd, " 毫秒", True, ("K18", "K19")),
    )
    for kind, name, pts, unit, pct, refs in body:
        seen = _change(pts, today, unit, 0, pct=pct)
        if seen:
            out.append(Observation(kind, name, seen, refs, f"最近 {WEEK + USUAL} 天的{name}"))
    seen = _change(readings.sleep_hours, today, " 小时", 1, usual_days=BEFORE, usual_name="前三周")
    if seen:
        out.append(Observation("sleep", "睡眠", f"{seen}（成年人建议每晚 {_f(SLEEP_ENOUGH)} 小时以上）",
                               ("K07",), "最近 4 周的睡眠记录"))  # fmt: skip
    seen = _change(
        readings.steps, today, " 步", 0, pct=True, usual_days=BEFORE, usual_name="前三周"
    )
    if seen:
        out.append(Observation("steps", "步数", seen, ("K21",), "最近 4 周的步数记录"))
    trend = weight_trend(readings.weight, today)
    if trend.ok and trend.value is not None and readings.weight:
        rate = _rate(trend, max(readings.weight)[1], profile.goal)
        refs = {"fat_loss": ("K37", "K87", "K16"), "muscle": ("K88", "K89")}.get(
            profile.goal or "", ()
        )
        out.append(Observation("weight", "体重", f"{trend.text}" + (f"；{rate}" if rate else ""), refs,
                               trend.data))  # fmt: skip
    done = [x for x in logs if x.done]
    this_week = sum(1 for x in done if today - timedelta(days=WEEK - 1) <= x.day <= today)
    earlier = sum(
        1
        for x in done
        if today - timedelta(days=WEEK + BEFORE - 1) <= x.day < today - timedelta(days=WEEK - 1)
    )
    if done:
        out.append(Observation("training", "训练次数",
                               f"最近 7 天练了 {this_week} 次，前三周平均每周 {_f(earlier / (BEFORE / WEEK))} 次",
                               data="最近 4 周的训练记录"))  # fmt: skip
    out += [Observation("illness", "生病", x) for x in illness]
    out += [Observation("event", "近期", e) for e in events]
    if not any((readings.resting_hr, readings.hrv_sdnn, readings.hrv_rmssd, readings.sleep_hours,
                readings.steps, readings.weight)):  # fmt: skip
        out.append(Observation("thin", "数据不够", "还没有心率、睡眠、步数、体重的记录"))
    return out
