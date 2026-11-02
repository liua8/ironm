"""特殊人群的硬规则（spec [2026-10-23] §95）：由代码认出情况、在计划检查里拦，不靠提示词。

只拦有明确依据的：未满 18 岁先学动作、不测极限〔K60〕；孕期避开易摔倒的、不憋气用力〔K110〕；
高血压不做大重量、不憋气〔K41〕；心脏病加大运动前先评估〔K14〕〔K56〕，落到"每组至少几次"是经验。
60 岁以上只提示〔K59〕〔K01〕。计时类、有氧、拉伸不算次数。判定只用代码，不调用模型。
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import date
from typing import Any

from ironm_agent.progression import rep_range
from ironm_agent.protools.movement import find
from ironm_agent.training import Plan, weekday_name

MINOR, SENIOR, PREGNANCY, CARDIAC, HYPERTENSION = (
    "minor",
    "senior",
    "pregnancy",
    "cardiac",
    "hypertension",
)
NAMES = {
    MINOR: "未满 18 岁",
    SENIOR: "60 岁以上",
    PREGNANCY: "孕期",
    CARDIAC: "有心脏病",
    HYPERTENSION: "有高血压",
}
# 每组至少几次：低于这个就是大重量
MIN_REPS = {MINOR: 6, PREGNANCY: 8, CARDIAC: 8, HYPERTENSION: 8}
WHY = {
    MINOR: "未成年人先学动作、不测极限〔K60〕",
    PREGNANCY: "孕期不憋气用力、不做跳跃这类易摔的动作〔K110〕；不做大重量",
    CARDIAC: "心脏病人加大强度前要先请医生评估〔K14〕",
    HYPERTENSION: "高血压不做大重量、不憋气〔K41〕",
}
MINOR_DAYS = 3  # 未成年每周最多几练（K60：每周 2–3 次不连续的日子）
_RISKS = {
    "pregnancy": PREGNANCY,
    "cardiac": CARDIAC,
    "hypertension": HYPERTENSION,
    "bp_high": HYPERTENSION,
}


def flags(profile: Any, risks: Sequence[Any], today: date) -> frozenset[str]:
    """这个人的特殊情况：出生日期看年龄；孕期、心脏病、高血压看档案里认出的风险（记忆和血压数据）。"""
    out = {_RISKS[r.key] for r in risks if r.key in _RISKS}
    age = profile.age(today) if profile is not None and hasattr(profile, "age") else None
    if age is not None and age < 18:
        out.add(MINOR)
    if age is not None and age >= 60:
        out.add(SENIOR)
    return frozenset(out)


def no_heavier(special: Collection[str]) -> bool:
    """训练中实时调整不加重的情况（和说疼一样）。"""
    return bool(set(special) & set(MIN_REPS))


def plan_problems(plan: Plan, special: Collection[str]) -> tuple[list[str], list[str]]:
    """（必须改的问题, 提示）。"""
    problems: list[str] = []
    hints: list[str] = []
    want = [(f, MIN_REPS[f]) for f in MIN_REPS if f in special]
    if MINOR in special and plan.days_per_week > MINOR_DAYS:
        problems.append(
            f"未满 18 岁：每周排了 {plan.days_per_week} 练，最多 {MINOR_DAYS} 练、隔天练〔K60〕"
        )
    for s in plan.sessions:
        for item in s.items:
            move = find(item.exercise)
            pattern = move.tag.pattern if move is not None else ""
            if PREGNANCY in special and pattern == "plyo":
                problems.append(
                    f"孕期：{weekday_name(s.day)}的{item.exercise}是跳跃类，容易摔，换成不跳的动作〔K110〕"
                )
            got = rep_range(item.reps)
            if got is None or pattern in ("cardio", "stretch"):
                continue
            for f, least in want:
                if got[0] < least:
                    problems.append(
                        f"{NAMES[f]}：{weekday_name(s.day)}的{item.exercise}每组 {item.reps} 次，属于大重量，"
                        f"改成每组至少 {least} 次的重量（{WHY[f]}）"
                    )
                    break
    if SENIOR in special:
        hints.append("60 岁以上：动作不练到力竭〔K59〕；65 岁以上每周至少 3 天加平衡练习〔K01〕")
    return problems, hints


def is_special(problem: str) -> bool:
    """这条检查问题是不是特殊人群的硬规则（出预览前最后一道）。"""
    return any(problem.startswith(NAMES[f] + "：") for f in MIN_REPS)


def rules_text(special: Collection[str]) -> str:
    """给模型看的一句：这个人有哪些特殊情况、计划和调整的硬规则（系统会按这些检查）。"""
    parts = []
    if MINOR in special:
        parts.append(
            f"未满 18 岁：每周最多 {MINOR_DAYS} 练、隔天练，每组至少 {MIN_REPS[MINOR]} 次，不测极限"
        )
    if PREGNANCY in special:
        parts.append(f"孕期：不排跳跃类动作，每组至少 {MIN_REPS[PREGNANCY]} 次，不憋气用力")
    if CARDIAC in special:
        parts.append(f"有心脏病：每组至少 {MIN_REPS[CARDIAC]} 次，加大强度前先请医生评估")
    if HYPERTENSION in special:
        parts.append(f"有高血压：每组至少 {MIN_REPS[HYPERTENSION]} 次，不憋气")
    if SENIOR in special:
        parts.append("60 岁以上：不练到力竭，每周加平衡练习")
    if not parts:
        return ""
    return (
        "这个人的特殊情况（系统按这些硬规则检查计划，不合格的不出预览；训练中不加重）："
        + "；".join(parts)
        + "。"
    )
