"""肌肉恢复度（spec [2026-10-23] §70 修改）：每次训练给肌肉加一份疲劳，疲劳按指数随时间消退，
恢复度 = 100% − 当前疲劳 ÷ 满疲劳。按规则计算，不调用模型。

- 疲劳：主要练到的每组记 1、辅助练到的每组记 0.5；乘用力程度（感受分）；4 周内没练过这块肌肉再乘 1.3。
- 消退：时间常数按肌肉类型（K49–K55 给的恢复时间范围，〔经验〕）：一次 5 组左右的训练后恢复到 90%
  约需上肢 40 小时、下肢多关节动作练到的 60 小时、腘绳肌做了硬拉类 72 小时、日常用得多的 28 小时。
- 每个人每块肌肉一个倍数（起点 1，0.7–1.5）：乘在时间常数上，按他说的"还酸 / 不酸了"校准。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal

from ironm_agent.protools.movement import find
from ironm_agent.protools.recovery import BASE_DAYS, DAILY, LENGTHENED
from ironm_agent.training import Plan, WorkoutLog

type Tier = Literal["high", "mid", "low", "ready"]
type ItemsOf = Callable[[WorkoutLog, Plan | None], list[tuple[str, int]]]

FULL = 8.0  # 约 8 组的疲劳算满（恢复度 0%）
ASSIST = 0.5
SESSION_HOUR = 18  # 只记了日期：训练时间按当天 18 点算
UNACCUSTOMED_DAYS = 28
UNACCUSTOMED = 1.3
# 时间常数（小时）：5 组后恢复到 90% 约需 1.83 个时间常数
TAU: dict[str, float] = {"upper": 22.0, "lower": 33.0, "hinge": 39.0, "daily": 15.0}
TIERS: tuple[tuple[int, Tier], ...] = ((40, "high"), (70, "mid"), (95, "low"))
RATE_MIN, RATE_MAX, RATE_STEP = 0.7, 1.5, 1.1
SORE_BUT_READY = 90  # 算出已恢复到这么多他却说还酸：在他身上恢复慢
FINE_BUT_TIRED = 60  # 算出还不到这么多他说不酸了：在他身上恢复快
# 训练水平（§69 建档后）作为起点
LEVEL_RATE: dict[str, float] = {"none": 1.3, "beginner": 1.3, "some": 1.0, "experienced": 0.85}


def effort(rpe: int | None) -> float:
    """用力程度：感受 6 分以下 0.8、7–8 分 1、9–10 分 1.3、没记 1。"""
    if rpe is None:
        return 1.0
    return 0.8 if rpe <= 6 else 1.3 if rpe >= 9 else 1.0


def kind_of(muscle: str, hinge: bool) -> str:
    if muscle in DAILY:
        return "daily"
    if hinge and muscle == "muscle.hamstrings":
        return "hinge"
    return "lower" if BASE_DAYS.get(muscle) == 2 else "upper"


@dataclass(frozen=True)
class Dose:
    muscle: str
    at: datetime
    load: float  # 这次给这块肌肉加的疲劳
    kind: str  # 消退快慢的类型


def doses(logs: Sequence[WorkoutLog], plan: Plan | None, items_of: ItemsOf) -> list[Dose]:
    """每次训练、每块肌肉的一份疲劳。logs 要包含往前 4 周，才能判断"4 周内没练过"。"""
    done = sorted((x for x in logs if x.done), key=lambda x: x.day)
    seen: dict[str, list[date]] = {}
    out: list[Dose] = []
    for log in done:
        main: dict[str, float] = {}
        assist: dict[str, float] = {}
        hinge: set[str] = set()
        for name, sets in items_of(log, plan):
            move = find(name)
            if move is None:
                continue
            for m in move.tag.muscles:
                main[m] = main.get(m, 0) + sets
                if move.tag.pattern in LENGTHENED:
                    hinge.add(m)
            for m in move.tag.assist:
                assist[m] = assist.get(m, 0) + sets
        at = datetime.combine(log.day, time(SESSION_HOUR))
        for m in set(main) | set(assist):
            before = [d for d in seen.get(m, []) if 0 < (log.day - d).days <= UNACCUSTOMED_DAYS]
            load = (main.get(m, 0) + ASSIST * assist.get(m, 0)) * effort(log.rpe)
            if not before:
                load *= UNACCUSTOMED
            out.append(Dose(m, at, load, kind_of(m, m in hinge)))
            seen.setdefault(m, []).append(log.day)
    return out


def recovery_pct(doses_of_muscle: Sequence[Dose], now: datetime, rate: float = 1.0) -> int:
    """这块肌肉现在的恢复度（0–100）。rate 乘在时间常数上：大于 1 恢复慢。"""
    left = 0.0
    for d in doses_of_muscle:
        hours = max(0.0, (now - d.at).total_seconds() / 3600)
        left += d.load * math.exp(-hours / (TAU[d.kind] * rate))
    return max(0, min(100, round(100 * (1 - left / FULL))))


def tier(pct: int) -> Tier:
    return next((t for line, t in TIERS if pct < line), "ready")


def recovery(
    logs: Sequence[WorkoutLog],
    now: datetime,
    plan: Plan | None,
    items_of: ItemsOf,
    muscles: Sequence[str],
    rates: Mapping[str, float] | None = None,
    base: float = 1.0,
) -> dict[str, int]:
    """每块肌肉现在的恢复度。只算最近 14 天的训练（再往前的疲劳早已消退）。"""
    rates = rates or {}
    recent = now - timedelta(days=14)
    by: dict[str, list[Dose]] = {}
    for d in doses(logs, plan, items_of):
        if d.at >= recent:
            by.setdefault(d.muscle, []).append(d)
    return {m: recovery_pct(by.get(m, []), now, base * rates.get(m, 1.0)) for m in muscles}


def calibrate(rate: float, pct: int, feel: str) -> float | None:
    """他说的和算的对不上时，调这块肌肉在他身上的恢复快慢；对得上返回 None。"""
    if feel == "sore" and pct >= SORE_BUT_READY:
        return min(RATE_MAX, round(rate * RATE_STEP, 3))
    if feel == "fine" and pct < FINE_BUT_TIRED:
        return max(RATE_MIN, round(rate / RATE_STEP, 3))
    return None
