"""计划检查：各肌群每周的组数与练几次、新手的天数与组数、同一肌群连续两天、伤病部位、器械、时长、
与当前计划相比改了什么。只检查、不改计划；问题交给训练教练自己改。"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Collection
from itertools import pairwise

from ironm_agent.exercises import Equipment
from ironm_agent.protools.movement import (
    JOINT_NAMES,
    Move,
    equipment_ok,
    find,
    stressed,
)
from ironm_agent.protools.result import Finding, Result
from ironm_agent.training import Plan, PlanItem, Session, weekday_name

# 增肌：每个肌群每周 10 组以上（K04）、至少练 2 次（K05）；新手每周 2–3 天、每个动作 1–3 组（K03）
WEEKLY_SETS = 10
WEEKLY_TIMES = 2
NOVICE_DAYS = 3
NOVICE_SETS = 3
# 估算时长：热身与放松各约 5 分钟（K06）；大动作组间休息 2–3 分钟、辅助动作 1–2 分钟（K03），每组做的时间约 1 分钟
WARMUP_MIN = 10
COMPOUND_SET_MIN = 3.5
ACCESSORY_SET_MIN = 2.5
SLACK = 1.1  # 估算时长超出可用时间 10% 以上才算问题
MAJOR = ("胸", "背", "股四头肌", "臀", "肩")
NOT_MUSCLE = frozenset({"有氧", "全身"})
# 写了限制的动作（"箱式""控制深度""不疼的范围"），伤病部位不算问题
_LIMITED = re.compile(r"限制|控制|不疼|无痛|减小幅度|小幅度|箱|浅蹲|半程|先别|替代|换成|扶")
_MINUTES = re.compile(r"(\d+)\s*分钟")


def _minutes(item: PlanItem, move: Move | None) -> float:
    if move is not None and move.tag.pattern == "cardio":
        m = _MINUTES.search(item.reps)
        return float(m.group(1)) if m else 15.0
    per = COMPOUND_SET_MIN if move is None or move.compound else ACCESSORY_SET_MIN
    return item.sets * per


def estimate_minutes(session: Session) -> float:
    return WARMUP_MIN + sum(_minutes(x, find(x.exercise)) for x in session.items)


def _volume(plan: Plan) -> tuple[dict[str, int], dict[str, list[int]], list[str]]:
    sets: dict[str, int] = defaultdict(int)
    days: dict[str, list[int]] = defaultdict(list)
    unknown: list[str] = []
    for s in plan.sessions:
        for item in s.items:
            move = find(item.exercise)
            if move is None:
                unknown.append(item.exercise)
                continue
            for g in move.tag.groups:
                if g in NOT_MUSCLE:
                    continue
                sets[g] += item.sets
                if s.day not in days[g]:
                    days[g].append(s.day)
    return dict(sets), dict(days), list(dict.fromkeys(unknown))


def weekly_sets(plan: Plan) -> dict[str, int]:
    """各肌群每周的组数（和计划检查同一种算法）。"""
    return _volume(plan)[0]


def back_to_back(plan: Plan) -> list[str]:
    """同一主要肌群连续两天练的肌群。"""
    days = _volume(plan)[1]
    return [g for g in MAJOR if g in days and _adjacent(days[g])]


def _adjacent(days: list[int]) -> bool:
    ds = sorted(days)
    return any((b - a) == 1 for a, b in pairwise(ds)) or (1 in ds and 7 in ds)


def changed_days(new: Plan, old: Plan) -> int:
    """新旧计划相比，有改动的天数（新增、去掉、内容变了都算）。"""
    a = {s.day: s for s in old.sessions}
    b = {s.day: s for s in new.sessions}
    return sum(
        1
        for d in set(a) | set(b)
        if (d in a) != (d in b) or (d in a and a[d].model_dump() != b[d].model_dump())
    )


def _diff(new: Plan, old: Plan) -> list[str]:
    out = []
    old_by = {s.day: s for s in old.sessions}
    new_by = {s.day: s for s in new.sessions}
    for day in range(1, 8):
        a, b = old_by.get(day), new_by.get(day)
        name = weekday_name(day)
        if a is None and b is None:
            continue
        if a is None and b is not None:
            out.append(f"{name}新增「{b.name}」")
        elif b is None and a is not None:
            out.append(f"{name}去掉「{a.name}」")
        elif a is not None and b is not None:
            was = {x.exercise: x.line() for x in a.items}
            now = {x.exercise: x.line() for x in b.items}
            changes = []
            if a.name != b.name:
                changes.append(f"「{a.name}」改为「{b.name}」")
            changes += [f"加了 {now[k]}" for k in now if k not in was]
            changes += [f"去掉 {k}" for k in was if k not in now]
            changes += [f"{was[k]} 改为 {now[k]}" for k in now if k in was and was[k] != now[k]]
            if changes:
                out.append(f"{name}：" + "；".join(changes))
    return out


def check_plan(
    plan: Plan,
    *,
    current: Plan | None = None,
    goal: str | None = None,
    novice: bool = False,
    injured: Collection[str] = (),
    equipment: frozenset[Equipment] | None = None,
    available_days: int | None = None,
    available_minutes: int | None = None,
    max_changed_days: int | None = None,
) -> Result:
    """max_changed_days：按复盘调整时每次最多改几天（spec [2026-10-23] §18）。"""
    problems: list[str] = []  # 必须改的
    hints: list[str] = []  # 建议看一看的
    sets, days, unknown = _volume(plan)
    findings: list[Finding] = []

    if sets:
        table = "、".join(
            f"{g} {sets[g]} 组（{len(days[g])} 次）" for g in sorted(sets, key=lambda g: -sets[g])
        )
        findings.append(
            Finding(
                "每周各肌群训练量",
                table,
                "每个动作的组数记到它主要练到的肌群上，按周累加；括号里是一周练到几次",
                f"计划《{plan.title}》，每周 {plan.days_per_week} 练",
                "动作库的标注（待审定）",
            )
        )
    if goal in ("muscle", "增肌"):
        few = [g for g in MAJOR if g in sets and sets[g] < WEEKLY_SETS]
        if few:
            hints.append(
                f"增肌时每个肌群每周 {WEEKLY_SETS} 组以上效果更好（K04），不够的："
                + "、".join(f"{g} {sets[g]} 组" for g in few)
            )
    if goal in ("muscle", "增肌", "strength", "力量"):
        once = [g for g in MAJOR if g in days and len(days[g]) < WEEKLY_TIMES]
        if once:
            hints.append(
                f"主要肌群每周至少练 {WEEKLY_TIMES} 次（K05），只练 1 次的：" + "、".join(once)
            )
    if goal not in ("endurance", "耐力") and plan.days_per_week >= 2:
        missing = [g for g in ("胸", "背", "股四头肌") if g not in sets]
        if missing:
            hints.append("一周里没练到：" + "、".join(missing))
    if novice:
        if plan.days_per_week > NOVICE_DAYS:
            hints.append(f"新手每周练 2–{NOVICE_DAYS} 天（K03），这份是 {plan.days_per_week} 天")
        heavy = [
            f"{weekday_name(s.day)}的{x.exercise} {x.sets} 组"
            for s in plan.sessions
            for x in s.items
            if x.sets > NOVICE_SETS
        ]
        if heavy:
            hints.append(f"新手每个动作 1–{NOVICE_SETS} 组（K03），超过的：" + "、".join(heavy))
    back_to_back = [g for g in MAJOR if g in days and _adjacent(days[g])]
    if back_to_back:
        hints.append(
            "同一肌群连续两天练，中间没有恢复的一天：" + "、".join(back_to_back) + "（经验规则）"
        )

    for s in plan.sessions:
        for item in s.items:
            move = find(item.exercise)
            if move is None:
                continue
            hurt = stressed(move, injured)
            if hurt and not _LIMITED.search(item.note + item.load + item.reps):
                parts = "、".join(JOINT_NAMES[j] for j in hurt)
                problems.append(
                    f"{weekday_name(s.day)}的{move.name}〔{move.ref}〕会给{parts}加负担，而他{parts}有伤：换动作或在备注里写明怎么限制"
                )
            if not equipment_ok(move, equipment):
                gear = "、".join(move.exercise.equipment)
                problems.append(f"{weekday_name(s.day)}的{move.name}需要{gear}，他没有")
        need = estimate_minutes(s)
        limit = min(x for x in (s.minutes, available_minutes) if x is not None)
        if need > limit * SLACK:
            problems.append(
                f"{weekday_name(s.day)}「{s.name}」估计要 {need:.0f} 分钟，超过了 {limit} 分钟：减少动作或组数"
            )
    if available_days is not None and plan.days_per_week > available_days:
        problems.append(f"排了每周 {plan.days_per_week} 练，他每周只能练 {available_days} 天")
    if unknown:
        hints.append("动作库里没有、没法检查的动作：" + "、".join(unknown))

    verdict = "通过" if not problems else f"有 {len(problems)} 个问题要改"
    lines = [*(f"问题：{x}" for x in problems), *(f"提示：{x}" for x in hints)]
    findings.append(
        Finding(
            "计划检查",
            verdict + ("。" + "；".join(lines) if lines else ""),
            "逐条检查：各肌群每周组数与次数、新手天数与组数、同一肌群连续两天、伤病部位、器械、"
            "每次时长（热身放松约 10 分钟，大动作每组约 3.5 分钟、辅助动作约 2.5 分钟，含组间休息）",
            "这份计划、他的伤病部位、器械与可用时间",
            "K03、K04、K05、K06；动作库",
        )
    )
    if current is not None and max_changed_days is not None:
        n = changed_days(plan, current)
        if n > max_changed_days:
            problems.append(
                f"改动了 {n} 天，按复盘调整每次最多改 {max_changed_days} 天：只保留最关键的改动"
            )
    if current is not None:
        changed = _diff(plan, current)
        findings.append(
            Finding(
                "和当前计划相比",
                "；".join(changed) if changed else "没有改动",
                "逐天对比两份计划的训练名称、动作与组次",
                "当前计划与这份新计划",
            )
        )
    entries = tuple(
        dict.fromkeys(m.ref for s in plan.sessions for x in s.items if (m := find(x.exercise)))
    )
    return Result(tuple(findings), entries=entries, problems=tuple(problems))
