"""调整有没有用（spec [2026-10-23] §89）：复盘写下的预期到期由代码对数据，4 周出一次阶段事实。

预期写成能核对的：看哪项数据、比多少大还是小、几天后看。到期时只用到期那天之前的数据算：
体重和其他每天测的看到期前 7 天的平均（至少 3 天有数），腰围、体脂看到期前 14 天里最近一次，
完成率看调整那天到到期按计划该练的日子，动作的估算最大重量看到期前 14 天里最好的一组。
数不够就是"数据不够"，不猜。阶段事实也都由代码算，模型只写小结。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date, timedelta
from statistics import mean
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from ironm_agent.metrics import Readings
from ironm_agent.protools.strength import epley
from ironm_agent.training import Plan, WorkoutLog

type Result = Literal["met", "missed", "unknown"]

AVG_DAYS = 7  # 每天测的看到期前几天的平均
AVG_MIN = 3  # 这几天里至少几天有数
LATEST_DAYS = 14  # 腰围、体脂、动作重量往前看几天
STAGE_DAYS = 28  # 阶段小结的间隔

# 能核对的数据：名字、单位、怎么取
METRICS: dict[str, tuple[str, str, str]] = {
    "weight": ("体重", "公斤", "avg"),
    "resting_hr": ("静息心率", "次/分", "avg"),
    "hrv": ("心率变异性", "毫秒", "avg"),
    "sleep": ("睡眠", "小时", "avg"),
    "steps": ("步数", "步", "avg"),
    "waist": ("腰围", "厘米", "latest"),
    "body_fat": ("体脂", "%", "latest"),
    "completion": ("按计划的完成率", "%", "completion"),
    "e1rm": ("估算最大重量", "公斤", "e1rm"),
}
_SERIES = {
    "weight": "weight",
    "resting_hr": "resting_hr",
    "hrv": "hrv_sdnn",
    "sleep": "sleep_hours",
    "steps": "steps",
    "waist": "waist",
    "body_fat": "body_fat",
}
RESULT_WORDS: dict[Result, str] = {"met": "达到了", "missed": "没达到", "unknown": "数据不够"}


class Check(BaseModel):
    """一条能核对的预期。"""

    metric: str
    op: Literal["<=", ">="]
    value: float
    days: int = Field(ge=3, le=42)
    exercise: str = ""

    def line(self) -> str:
        name, unit, _ = METRICS[self.metric]
        what = f"{self.exercise}的{name}" if self.metric == "e1rm" else name
        word = "不高于" if self.op == "<=" else "不低于"
        return f"{self.days} 天后{what}{word} {_num(self.value)} {unit}"


def parse_check(raw: Any) -> Check | None:
    """模型写的预期 → Check；写错的返回 None（照样执行这条调整，只是不核对）。"""
    if not isinstance(raw, dict) or raw.get("metric") not in METRICS:
        return None
    try:
        got = Check.model_validate(raw)
    except ValidationError:
        return None
    if got.metric == "e1rm" and not got.exercise.strip():
        return None
    return got


def _num(x: float) -> str:
    return f"{x:.0f}" if abs(x - round(x)) < 0.05 or abs(x) >= 100 else f"{x:.1f}"


def _window(points: Sequence[tuple[date, float]], end: date, days: int) -> list[tuple[date, float]]:
    return sorted(p for p in points if end - timedelta(days=days - 1) <= p[0] <= end)


def _best_e1rm(logs: Sequence[WorkoutLog], exercise: str, start: date, end: date) -> float | None:
    best: float | None = None
    for log in logs:
        if not (start <= log.day <= end):
            continue
        for item in log.items:
            if item.exercise != exercise:
                continue
            sets = [(s.weight_kg, s.reps) for s in item.done_sets if s.weight_kg and s.reps]
            if not sets and item.weight_kg and re.fullmatch(r"\d+", item.reps or ""):
                sets = [(item.weight_kg, int(item.reps))]
            for w, r in sets:
                e = epley(float(w), int(r))
                best = e if best is None else max(best, e)
    return best


def measure(
    check: Check,
    start: date,
    due: date,
    readings: Readings,
    logs: Sequence[WorkoutLog],
    plan: Plan | None,
) -> tuple[float | None, str]:
    """按到期那天之前的数据算这项（算不了返回 None 和原因）。"""
    name, unit, how = METRICS[check.metric]
    if how == "avg":
        got = _window(getattr(readings, _SERIES[check.metric]), due, AVG_DAYS)
        if len(got) < AVG_MIN:
            return None, f"到期前 {AVG_DAYS} 天只有 {len(got)} 天有{name}数据"
        v = mean(x for _, x in got)
        return v, f"到期前 {AVG_DAYS} 天平均 {_num(v)} {unit}"
    if how == "latest":
        got = _window(getattr(readings, _SERIES[check.metric]), due, LATEST_DAYS)
        if not got:
            return None, f"到期前 {LATEST_DAYS} 天没有{name}数据"
        d, v = got[-1]
        return v, f"{d.month} 月 {d.day} 日是 {_num(v)} {unit}"
    if how == "completion":
        if plan is None:
            return None, "没有训练计划"
        days = [start + timedelta(days=i) for i in range(1, (due - start).days + 1)]
        planned = [d for d in days if plan.session_on(d) is not None]
        if not planned:
            return None, "这段时间按计划没有要练的日子"
        done = {x.day for x in logs if x.done}
        hit = sum(1 for d in planned if d in done)
        v = hit / len(planned) * 100
        return v, f"按计划该练 {len(planned)} 次，练了 {hit} 次，完成率 {v:.0f}%"
    best = _best_e1rm(logs, check.exercise, due - timedelta(days=LATEST_DAYS - 1), due)
    if best is None:
        return None, f"到期前 {LATEST_DAYS} 天没有{check.exercise}的记录"
    return best, f"到期前 {LATEST_DAYS} 天最好的一组估算 {_num(best)} {unit}"


def judge(check: Check, value: float | None) -> Result:
    if value is None:
        return "unknown"
    ok = value <= check.value if check.op == "<=" else value >= check.value
    return "met" if ok else "missed"


# ---- 4 周阶段事实 -----------------------------------------------------------------------------


def stage_due(
    last: date | None, since: date | None, logs: Sequence[WorkoutLog], today: date
) -> bool:
    """该出阶段小结了：距上次小结（没有就从计划开始、再没有就从第一次训练记录）满 28 天。"""
    first = min((x.day for x in logs), default=None)
    start = last or since or first
    return start is not None and (today - start).days >= STAGE_DAYS


def _halves(points: Sequence[tuple[date, float]], today: date) -> tuple[list[float], list[float]]:
    early = [v for d, v in points if today - timedelta(days=27) <= d <= today - timedelta(days=14)]
    late = [v for d, v in points if today - timedelta(days=13) <= d <= today]
    return early, late


def stage_facts(
    readings: Readings,
    logs: Sequence[WorkoutLog],
    today: date,
    *,
    goal_line: str = "",
    adjustments: Sequence[str] = (),
) -> list[str]:
    """这 4 周的阶段事实（前两周和后两周比）；没有数的项不写。"""
    out: list[str] = []
    recent = [x for x in logs if today - timedelta(days=STAGE_DAYS - 1) <= x.day <= today]
    out.append(f"这 4 周练了 {sum(1 for x in recent if x.done)} 次")
    counts: dict[str, int] = {}
    for log in recent:
        for item in log.items:
            counts[item.exercise] = counts.get(item.exercise, 0) + 1
    for name in sorted(counts, key=lambda n: -counts[n])[:3]:
        a = _best_e1rm(recent, name, today - timedelta(days=27), today - timedelta(days=14))
        b = _best_e1rm(recent, name, today - timedelta(days=13), today)
        if a is not None and b is not None:
            out.append(f"{name}估算最大重量：前两周 {_num(a)} 公斤，后两周 {_num(b)} 公斤")
    for key, (name, unit, _) in METRICS.items():
        if key not in ("weight", "waist", "sleep", "resting_hr"):
            continue
        early, late = _halves(getattr(readings, _SERIES[key]), today)
        if early and late:
            out.append(
                f"{name}：前两周平均 {_num(mean(early))} {unit}，后两周平均 {_num(mean(late))} {unit}"
            )
    if goal_line:
        out.append(f"目标进度：{goal_line}")
    out += [f"这 4 周管家的调整：{x}" for x in adjustments] or ["这 4 周管家没有调整"]
    return out
