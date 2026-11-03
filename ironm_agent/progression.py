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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from ironm_agent.protools.movement import find
from ironm_agent.training import Plan, PlanItem, SetDone, WorkoutLog

type Action = Literal["up", "more", "hold", "down"]

UP = 0.05
UP_MAX = 0.10
DOWN = 0.10
DOWN_MAX = 0.30  # 管家定的一次最多减多少（§132）
REPS_CAP = 30  # 管家定的每组次数上限（§132）
_REPS_ONLY = re.compile(r"\d+(?:\s*[-–~～到至]\s*\d+)?")
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
    by: str = "rule"  # rule：按规则算的；coach：管家练完后定的（§132）

    def text(self) -> str:
        w = f"{self.weight_kg:g} 公斤 × " if self.weight_kg else ""
        return f"{w}{self.reps} 次 × {self.sets} 组"

    def line(self) -> str:
        who = "〔管家定的〕" if self.by == "coach" else ""
        return f"{self.exercise} 下次 {self.text()}（{self.why}）{who}"


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


class Decided(BaseModel):
    """管家练完后定的一个动作的下次目标（§132）。after、mark、plan 记着它依据的是哪天、那天记了哪些组、
    当时计划的组次：同一天又记了、删了重记、改了计划，都对不上，回到规则。"""

    exercise: str
    sets: int = Field(ge=1, le=10)
    reps: str = Field(min_length=1, max_length=20)
    weight_kg: float | None = Field(default=None, ge=0, le=500)
    why: str = Field(default="", max_length=120)
    after: date
    mark: str = ""
    plan: str = ""

    def holds(self, item: PlanItem, logs: Sequence[WorkoutLog]) -> bool:
        """还算数：依据的就是这个动作最近一次的记录，计划的组次也没改。"""
        seen = latest(item.exercise, logs)
        return (seen is not None and self.after == seen[0] and self.plan == plan_mark(item)
                and self.mark == day_mark(item.exercise, logs, seen[0]))  # fmt: skip


def plan_mark(item: PlanItem) -> str:
    return f"{item.sets}×{item.reps}"


def day_mark(exercise: str, logs: Sequence[WorkoutLog], day: date) -> str:
    """那天这个动作记下的每组（几条记录合在一起，顺序无关）：同一天又记了或改了，标记就变。"""
    rows = []
    for log in logs:
        if log.done and log.day == day:
            for it in log.items:
                if _same(it.exercise, exercise):
                    rows += [f"{x.weight_kg or 0:g}x{x.reps}" for x in it.performed()]
    return ",".join(sorted(rows))


def latest(exercise: str, logs: Sequence[WorkoutLog]) -> tuple[date, float | None] | None:
    """这个动作最近一次记了每组的那天和那天最重的一组（同一天几条记录一起看，没有重量为 None）。"""
    hist = history(exercise, logs)
    if not hist:
        return None
    day = hist[0][0]
    weights = [x.weight_kg for log in logs if log.done and log.day == day for it in log.items
               if _same(it.exercise, exercise) for x in it.performed() if x.weight_kg]  # fmt: skip
    return day, (max(weights) if weights else None)


def check_decided(item: PlanItem, d: Decided, last: float | None) -> str:
    """管家定的下次目标过不过得了代码这一关（§132）；过了返回空字符串，否则返回退回的原因。"""
    if not _same(item.exercise, d.exercise):
        return f"{d.exercise} 不在当前计划里"
    if not d.why.strip():
        return "要写原因（像当面对他说）"
    if rep_range(item.reps) is None:  # 按秒、分钟、距离计的：次数照计划
        if d.reps != item.reps:
            return f"这个动作按「{item.reps}」计，次数照计划写"
    elif (
        not _REPS_ONLY.fullmatch(d.reps) or (rng := rep_range(d.reps)) is None or rng[1] > REPS_CAP
    ):
        return f"次数要写成 8–12 或 10 这样（不超过 {REPS_CAP} 次）"
    if last and not d.weight_kg:
        return f"上次用了 {_fmt(last)} 公斤，重量不能去掉；要减重写具体公斤"
    if d.weight_kg and last and d.weight_kg > last * (1 + UP_MAX) + 1e-9:
        return f"一次加重不超过上次重量（{_fmt(last)} 公斤）的一成〔K03〕"
    if d.weight_kg and last and d.weight_kg < last * (1 - DOWN_MAX) - 1e-9:
        return f"一次减重不超过上次重量（{_fmt(last)} 公斤）的三成；不舒服到要减更多就先停这个动作、问他"
    if d.weight_kg and not last:
        return "上次没用重量，这里不新加重量（要加先改计划）"
    return ""


def targets(
    plan: Plan | None, logs: Sequence[WorkoutLog], decided: Mapping[str, Decided] | None = None
) -> dict[str, Target]:
    """计划里每个动作的下次目标（同名动作只算一次）。管家按最新一次记录定过的用它的（§132），
    之后又有新记录、或没定过的，按规则算。"""
    out: dict[str, Target] = {}
    for s in plan.sessions if plan else ():
        for item in s.items:
            if item.exercise in out:
                continue
            rule = next_target(item, logs)
            d = (decided or {}).get(item.exercise)
            seen = latest(item.exercise, logs)
            if d is not None and seen is not None and d.holds(item, logs):
                last = seen[1]
                move: Action = ("up" if d.weight_kg and last and d.weight_kg > last
                                else "down" if d.weight_kg and last and d.weight_kg < last else "hold")  # fmt: skip
                mine = Target(
                    item.exercise,
                    d.sets,
                    d.reps,
                    d.weight_kg,
                    move,
                    d.why or "管家按这次的记录定的",
                    by="coach",
                )
                if (
                    rule is not None and rule.text() != mine.text()
                ):  # 和规则不同：说明里带上规则算的（§132 需求 5）
                    mine = replace(mine, why=f"{mine.why}（规则算的是 {rule.text()}）")
                out[item.exercise] = mine  # fmt: skip
            elif rule is not None:
                out[item.exercise] = rule
    return out


def target_lines(
    plan: Plan | None,
    logs: Sequence[WorkoutLog],
    today: date,
    decided: Mapping[str, Decided] | None = None,
) -> list[str]:
    """共享档案里的下次目标：今天有训练只列今天的动作，否则列全部（最多 8 个）。"""
    found = targets(plan, logs, decided)
    s = plan.session_on(today) if plan else None
    names = [x.exercise for x in s.items] if s else list(found)
    shown = [found[n].line() for n in dict.fromkeys(names) if n in found][:8]
    return (
        ["下次目标（管家练完后定的标了出来，其余按最近两次记录的规则计算）：" + "；".join(shown)]
        if shown
        else []
    )
