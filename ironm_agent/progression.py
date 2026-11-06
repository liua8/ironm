"""下次目标（spec [2026-10-23] §132、§163 需求 6）：每个动作下次练多重、几次、几组。

只由管家定：练完后叫醒管家定（next_targets），代码只核对上下限（加重一次不超过一成〔K03〕、减重不超过三成、
有重量的不去掉、没重量的不新加）。管家没定、或定的已经不适用（之后又记了、改了计划），下次照上次实际做的
重量和次数，不按规则算进阶。不调用模型；只看填了每组次数（或"3 组 × 8 次"这样能展开）的记录。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from ironm_agent.protools.movement import find
from ironm_agent.training import Plan, PlanItem, SetDone, WorkoutLog

type Action = Literal["up", "more", "hold", "down"]

UP_MAX = 0.10  # 管家定的一次最多加多少〔K03〕
DOWN_MAX = 0.30  # 管家定的一次最多减多少（§132）
REPS_CAP = 30  # 管家定的每组次数上限（§132）
_REPS_ONLY = re.compile(r"\d+(?:\s*[-–~～到至]\s*\d+)?")
_RANGE = re.compile(r"(\d+)\s*(?:[-–~～到至]\s*(\d+))?")


@dataclass(frozen=True)
class Target:
    exercise: str
    sets: int
    reps: str
    weight_kg: float | None
    action: Action
    why: str
    by: str = "last"  # coach：管家练完后定的（§132）；last：管家没定，照上次（§163 需求 6）

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


def _fmt(x: float) -> str:
    return f"{x:g}"


def last_target(item: PlanItem, logs: Sequence[WorkoutLog]) -> Target | None:
    """管家没定（或定的已经不适用）时的下次目标：照上次实际做的重量和次数，不算进阶（§163 需求 6）。
    重量取上次最重的一组，次数取那个重量下做到的次数，组数照计划；按秒、分钟、距离计的、没记过的为 None。"""
    if rep_range(item.reps) is None:
        return None
    seen = latest(item.exercise, logs)
    if seen is None:
        return None
    day, w = seen
    done = [x for log in logs if log.done and log.day == day for it in log.items
            if _same(it.exercise, item.exercise) for x in it.performed()]  # fmt: skip
    at = [x.reps for x in done if (x.weight_kg or None) == w and x.reps]
    if not at:
        return None
    lo, hi = min(at), max(at)
    reps = str(lo) if lo == hi else f"{lo}–{hi}"
    return Target(
        item.exercise,
        item.sets,
        reps,
        w,
        "hold",
        f"照上次：{day.month}月{day.day}日做的",
        by="last",
    )


def coach_target(
    item: PlanItem, logs: Sequence[WorkoutLog], decided: Mapping[str, Decided] | None
) -> Target | None:
    """管家按最新一次记录定的下次目标（§132）；没定过、之后又有新记录、改了计划的为 None。"""
    d = (decided or {}).get(item.exercise)
    seen = latest(item.exercise, logs)
    if d is None or seen is None or not d.holds(item, logs):
        return None
    last = seen[1]
    move: Action = ("up" if d.weight_kg and last and d.weight_kg > last
                    else "down" if d.weight_kg and last and d.weight_kg < last else "hold")  # fmt: skip
    return Target(
        item.exercise,
        d.sets,
        d.reps,
        d.weight_kg,
        move,
        d.why or "管家按这次的记录定的",
        by="coach",
    )


class Decided(BaseModel):
    """管家练完后定的一个动作的下次目标（§132）。after、mark、plan 记着它依据的是哪天、那天记了哪些组、
    当时计划的组次：同一天又记了、删了重记、改了计划，都对不上，照上次（§163 需求 6）。"""

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
    没定过、之后又有新记录的照上次（§163 需求 6）。"""
    out: dict[str, Target] = {}
    for s in plan.sessions if plan else ():
        for item in s.items:
            if item.exercise in out:
                continue
            if (t := coach_target(item, logs, decided) or last_target(item, logs)) is not None:
                out[item.exercise] = t
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
        ["下次目标（管家练完后定的标了出来，其余照上次的重量和次数）：" + "；".join(shown)]
        if shown
        else []
    )
