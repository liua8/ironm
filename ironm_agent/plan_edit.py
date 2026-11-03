"""计划页直接改（spec [2026-10-23] §106）：换动作、调组次、去掉、排顺序；只改今天或以后都改。

代码按先后一条条套（套用规则和对话里改计划同一套，§45），换动作查器械和伤处；改完按特殊情况的
硬规则（§95）查一遍，这次改动新带来的问题挡下，原来就有的不算；去掉动作后没练到、时长超了只提醒。
不调用模型、不读写存储。
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import date

from ironm_agent.exercises import Equipment
from ironm_agent.plan_ops import Op, apply
from ironm_agent.progression import history
from ironm_agent.protools.movement import find, ranked
from ironm_agent.protools.plan_check import check_plan
from ironm_agent.training import Plan, PlanEdit, PlanItem, Session, WorkoutLog, weekday_name

MAX_ALTERNATIVES = 6
_REMIND = (
    "没练到",
    "分钟",
)  # 去掉动作后某肌群没练到、时长超了：是他要的或只是偏多，只提醒（§104 超上限只提示）


@dataclass
class Edited:
    plan: Plan
    lines: list[str] = field(default_factory=list)  # 改了什么
    notes: list[str] = field(default_factory=list)  # 代码替他做的修正（换成的动作不合适时用了替代）
    skipped: list[str] = field(default_factory=list)  # 没改成的原因
    problems: list[str] = field(default_factory=list)  # 这次改动新带来的、要挡下的问题
    warnings: list[str] = field(default_factory=list)  # 只提醒的

    @property
    def ok(self) -> bool:
        return bool(self.lines) and not self.problems


def _on(plan: Plan, day: int) -> Session | None:
    return next((s for s in plan.sessions if s.day == day), None)


def reorder(plan: Plan, day: int, names: Sequence[str]) -> tuple[Plan, str]:
    """把那天的动作排成 names 的顺序；names 必须正好是那天的这些动作，顺序没变时不改。"""
    s = _on(plan, day)
    if s is None:
        return plan, ""
    now = [x.exercise for x in s.items]
    if sorted(names) != sorted(now) or list(names) == now:
        return plan, ""
    by = {x.exercise: x for x in s.items}
    moved = s.model_copy(update={"items": [by[n] for n in names]})
    sessions = [moved if x.day == day else x for x in plan.sessions]
    return plan.model_copy(update={"sessions": sessions}), (
        f"{weekday_name(day)}「{s.name}」顺序改成：{'、'.join(names)}"
    )


def edit(
    plan: Plan,
    day: int,
    edits: Sequence[PlanEdit],
    *,
    equipment: frozenset[Equipment] | None = None,
    injured: Collection[str] = (),
    special: Collection[str] = (),
    check: bool = True,
) -> Edited:
    """按先后套用（先改组数再换动作、先换再改换上的那个都对）；check=False 时不查（已经查过的）。"""
    out = Edited(plan)
    cur = plan
    touched: set[str] = set()  # 改到的动作名（换下的、换上的、改组次的）
    for e in edits:
        if e.kind == "order":
            cur, line = reorder(cur, day, e.names)
            if line:
                out.lines.append(line)
            else:
                out.skipped.append("顺序没有变化")
            continue
        s = _on(cur, day)
        if e.kind == "remove" and (not e.exercise or (s is not None and len(s.items) <= 1)):
            out.skipped.append("这天只剩这一个动作，不能去掉")  # 计划页只去掉动作，不删整天
            continue
        op = Op(kind=e.kind, day=day, exercise=e.exercise, to=e.to, sets=e.sets, reps=e.reps)
        got = apply(cur, [op], equipment=equipment, injured=injured)
        before = {x.exercise for x in s.items} if s is not None else set()
        after = _on(got.plan, day)
        touched |= {e.exercise} | ({x.exercise for x in after.items} - before if after else set())
        cur = got.plan
        out.lines += got.lines
        out.notes += got.notes
        out.skipped += got.skipped
    out.plan = cur
    if check and out.lines:

        def found(p: Plan) -> tuple[str, ...]:
            return check_plan(
                p, current=plan, injured=injured, equipment=equipment, special=special
            ).problems

        # 原来就有的不算新问题：把改到的动作名抹掉再比（换了名字的老问题，比如原来每组就 5 次，不挡）
        def plain(x: str) -> str:
            for n in sorted(touched, key=len, reverse=True):
                x = x.replace(n, "□") if n else x
            return x

        had = {plain(x) for x in found(plan)}
        new = [x for x in found(cur) if plain(x) not in had]
        out.warnings = [x for x in new if any(w in x for w in _REMIND)]
        out.problems = [x for x in new if x not in out.warnings]
        s = _on(cur, day)  # 换上的动作本身要适合他（孕期不做跳跃类等），不管原来那个合不合适
        swapped = touched - {e.exercise for e in edits}
        for n in sorted(swapped & {x.exercise for x in (s.items if s else [])}):
            out.problems += [x for x in _move_problems(n, day, equipment, injured, special)
                             if x not in out.problems]  # fmt: skip
    return out


def _move_problems(
    name: str,
    day: int,
    equipment: frozenset[Equipment] | None,
    injured: Collection[str],
    special: Collection[str],
) -> tuple[str, ...]:
    """只放这一个动作（每组 12 次，不算大重量）查一遍：它本身对他合不合适。"""
    probe = Session(day=day, name="检查", items=[PlanItem(exercise=name, sets=1, reps="12")])
    plan = Plan(title="检查", days_per_week=1, sessions=[probe])
    return check_plan(plan, injured=injured, equipment=equipment, special=special).problems


def apply_today(session: Session, edits: Sequence[PlanEdit]) -> tuple[Session, list[PlanEdit]]:
    """把今天存下的改动按先后套到今天那一次上（存的时候已经查过器械、伤处和特殊情况，这里不再查）；
    返回（改过的那一次, 套上了的改动）。之后计划本身又改了、某条套不上时跳过它。"""
    cur = session
    kept: list[PlanEdit] = []
    for e in edits:
        got = edit(Plan(title="今天", days_per_week=1, sessions=[cur]), cur.day, [e], check=False)
        if got.lines:
            cur, kept = got.plan.sessions[0], [*kept, e]
    return cur, kept


def today_session(session: Session, edits: Sequence[PlanEdit]) -> Session:
    return apply_today(session, edits)[0]


def with_today(plan: Plan, edits: Sequence[PlanEdit], today: date) -> Plan:
    """今天那一次换成改过的；其他天不变。"""
    s = plan.session_on(today)
    if s is None or not edits:
        return plan
    got = today_session(s, edits)
    return plan.model_copy(update={"sessions": [got if x is s else x for x in plan.sessions]})


def last_text(name: str, logs: Sequence[WorkoutLog]) -> str:
    """这个动作上次每组做了多少；没做过时为空。"""
    last = history(name, logs)
    if not last:
        return ""
    return "上次 " + "、".join(
        (f"{x.seconds} 秒" if not x.reps and x.seconds else
         f"{x.weight_kg:g}×{x.reps}" if x.weight_kg else f"{x.reps} 次") for x in last[0][1]
    )  # fmt: skip


def alternatives(
    plan: Plan,
    day: int,
    exercise: str,
    *,
    equipment: frozenset[Equipment] | None = None,
    injured: Collection[str] = (),
    special: Collection[str] = (),
    logs: Sequence[WorkoutLog] = (),
) -> list[dict[str, object]]:
    """能替代它的动作：同一类优先，按器械和伤处排（§45 同一套），会被挡下的、那天已经有的不列。"""
    base = find(exercise)
    s = _on(plan, day)
    if base is None or s is None:
        return []
    out: list[dict[str, object]] = []
    for m in ranked(base, equipment=equipment, injured=injured, k=MAX_ALTERNATIVES * 3):
        trial = edit(plan, day, [PlanEdit(kind="swap", exercise=exercise, to=m.name)],
                     equipment=equipment, injured=injured, special=special)  # fmt: skip
        got = _on(trial.plan, day)
        if not trial.ok or got is None or all(x.exercise != m.name for x in got.items):
            continue
        out.append({"name": m.name, "same": m.tag.pattern == base.tag.pattern,
                    "equipment": list(m.exercise.equipment), "level": m.exercise.level,
                    "part": m.exercise.part, "last": last_text(m.name, logs)})  # fmt: skip
        if len(out) >= MAX_ALTERNATIVES:
            break
    return out
