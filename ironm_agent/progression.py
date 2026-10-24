"""自动进阶（spec [2026-10-23] §18 需求 4）：按最近两次的每组重量和次数，用规则给每个动作"下次目标"。

- 连续两次每组都比目标次数上限多做 1 次以上：加重约 5%（2–10% 之内，K03），按器械取整：
  杠铃、器械 2.5 公斤，哑铃、壶铃 10 公斤以下 1 公斤、以上 2 公斤；取整后超过 10%，
  或者没有重量（自重、弹力带）时，改为加次数（每组多 2 次，次数上限到 20 后改为加 1 组）；
- 上次有组没做到目标次数下限：保持；连续两次没做到：减重约 10%（经验）；
- 其余保持，写明还差什么。
不调用模型；只看填了每组次数（或"3 组 × 8 次"这样能展开）的记录。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from ironm_agent.protools.movement import find
from ironm_agent.training import Plan, PlanItem, SetDone, WorkoutLog

type Action = Literal["up", "more", "hold", "down"]

UP = 0.05
UP_MAX = 0.10
DOWN = 0.10
MAX_REPS = 20
MAX_SETS = 6
_RANGE = re.compile(r"(\d+)\s*(?:[-–~～到至]\s*(\d+))?")


@dataclass(frozen=True)
class Target:
    exercise: str
    sets: int
    reps: str
    weight_kg: float | None
    action: Action
    why: str

    def text(self) -> str:
        w = f"{self.weight_kg:g} 公斤 × " if self.weight_kg else ""
        return f"{w}{self.reps} 次 × {self.sets} 组"

    def line(self) -> str:
        return f"{self.exercise} 下次 {self.text()}（{self.why}）"


def rep_range(reps: str) -> tuple[int, int] | None:
    """计划里的次数："8–12" → (8, 12)，"10" → (10, 10)；按秒、分钟、距离计的不算。"""
    if re.search(r"秒|分钟|米|公里", reps):
        return None
    m = _RANGE.search(reps)
    if m is None:
        return None
    lo = int(m.group(1))
    hi = int(m.group(2)) if m.group(2) else lo
    return (lo, hi) if 0 < lo <= hi else None


def step_for(exercise: str, weight: float) -> float | None:
    """加减重量的最小单位；自重、弹力带这类没有可加的重量时为 None。"""
    move = find(exercise)
    gear: tuple[str, ...] = move.exercise.equipment if move else ()
    named = tuple(
        g for g in ("杠铃", "哑铃", "壶铃") if g in exercise
    )  # 名字里写了用什么，以名字为准
    small = 1.0 if weight < 10 else 2.0
    if named:
        return 2.5 if named[0] == "杠铃" else small
    if "哑铃" in gear or "壶铃" in gear:  # 几种器械都行时按小的单位加，稳妥
        return small
    if "杠铃" in gear or "器械" in gear:
        return 2.5
    return None


def _same(a: str, b: str) -> bool:
    if a == b:
        return True
    ma, mb = find(a), find(b)
    return ma is not None and mb is not None and ma.exercise.id == mb.exercise.id


def history(exercise: str, logs: Sequence[WorkoutLog]) -> list[tuple[date, list[SetDone]]]:
    """这个动作最近几次（新的在前）每组做了多少。"""
    out = []
    for log in sorted((x for x in logs if x.done), key=lambda x: x.day, reverse=True):
        for it in log.items:
            if _same(it.exercise, exercise) and (sets := it.performed()):
                out.append((log.day, sets))
                break
    return out


def _round(x: float, step: float) -> float:
    return round(round(x / step) * step, 2)


def _fmt(x: float) -> str:
    return f"{x:g}"


def next_target(item: PlanItem, logs: Sequence[WorkoutLog]) -> Target | None:
    rng = rep_range(item.reps)
    hist = history(item.exercise, logs)
    if rng is None or not hist:
        return None
    lo, hi = rng
    last = hist[0][1]
    weights = [x.weight_kg for x in last if x.weight_kg]
    w = max(weights) if weights else None

    def beat(sets: list[SetDone]) -> bool:
        return len(sets) >= item.sets and all(x.reps >= hi + 1 for x in sets)

    def missed(sets: list[SetDone]) -> bool:
        return min(x.reps for x in sets) < lo

    def keep(action: Action, why: str, weight: float | None = w) -> Target:
        return Target(item.exercise, item.sets, item.reps, weight, action, why)

    if len(hist) >= 2 and beat(last) and beat(hist[1][1]):
        done = f"最近两次每组都做到 {hi + 1} 次以上（目标上限 {hi} 次）"
        step = step_for(item.exercise, w) if w else None
        if w and step:
            inc = max(step, _round(w * UP, step))
            if inc / w <= UP_MAX:
                return keep("up", f"{done}：加重 {_fmt(inc)} 公斤（约 {inc / w:.0%}）", w + inc)
        why = f"{done}，重量没法再小幅增加" if w else done
        if hi + 2 <= MAX_REPS:
            reps = f"{lo + 2}–{hi + 2}" if lo != hi else str(hi + 2)
            return Target(item.exercise, item.sets, reps, w, "more", f"{why}：每组多做 2 次")
        if item.sets < MAX_SETS:
            return Target(item.exercise, item.sets + 1, item.reps, w, "more", f"{why}：加 1 组")
        return keep("hold", f"{why}，组数和次数都到上限了：可以换更难的变式")
    if missed(last):
        if len(hist) >= 2 and missed(hist[1][1]) and w:
            step = step_for(item.exercise, w) or 0.5
            down = _round(w * (1 - DOWN), step)
            if down >= w:
                down = round(w - step, 2)
            if down > 0:
                why = f"连续两次有组没做到 {lo} 次（目标下限）：减重约 10%，动作做标准"
                return keep("down", why, down)
        return keep("hold", f"上次有组没做到 {lo} 次（目标下限）：先保持")
    best = min(x.reps for x in last)
    if beat(last):
        return keep("hold", f"上次每组都超过 {hi} 次，下次也做到就加重")
    return keep("hold", f"上次最少的一组做了 {best} 次：每组做到 {hi + 1} 次以上、连续两次后加重")


def targets(plan: Plan | None, logs: Sequence[WorkoutLog]) -> dict[str, Target]:
    """计划里每个动作的下次目标（同名动作只算一次）。"""
    out: dict[str, Target] = {}
    for s in plan.sessions if plan else ():
        for item in s.items:
            if item.exercise not in out and (t := next_target(item, logs)) is not None:
                out[item.exercise] = t
    return out


def target_lines(plan: Plan | None, logs: Sequence[WorkoutLog], today: date) -> list[str]:
    """共享档案里的下次目标：今天有训练只列今天的动作，否则列全部（最多 8 个）。"""
    found = targets(plan, logs)
    s = plan.session_on(today) if plan else None
    names = [x.exercise for x in s.items] if s else list(found)
    shown = [found[n].line() for n in dict.fromkeys(names) if n in found][:8]
    return ["下次目标（按最近两次记录的规则计算）：" + "；".join(shown)] if shown else []
