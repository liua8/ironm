"""营养计算：按体重和目标的蛋白质、每餐蛋白质、按训练量的碳水、补剂按体重的剂量、运动前补水。

热量（基础代谢、每日总消耗、目标热量）已经在指标计算里，这里不重复。
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Literal

from ironm_agent.metrics import PROTEIN, per_meal_protein
from ironm_agent.protools.result import Finding, Result

type Item = Literal["protein", "carbs", "creatine", "caffeine", "beta_alanine", "hydration"]
ITEMS: tuple[Item, ...] = ("protein", "carbs", "creatine", "caffeine", "beta_alanine", "hydration")


def _g(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".")


def protein_range(w: float, goal: str | None) -> tuple[int, int, float, float]:
    """与数据页同一份系数（metrics.PROTEIN）：增肌、力量、减脂 1.6–2.0，其余 1.4–1.6 克/公斤。"""
    lo, hi = PROTEIN.get(goal or "", (1.4, 1.6))
    return round(w * lo), round(w * hi), lo, hi


def _protein(w: float, goal: str | None) -> list[Finding]:
    data = f"体重 {_g(w)} 公斤"
    a, b, lo, hi = protein_range(w, goal)
    out = [
        Finding(
            "每天蛋白质",
            f"每天约 {a}–{b} 克",
            f"{_g(w)}×{lo:g}={a}，{_g(w)}×{hi:g}={b}（每公斤体重 {lo:g}–{hi:g} 克，与数据页同一份计算）",
            data,
            "K09（运动人群每天 1.4–2.0 克/公斤）",
        ),
        Finding(
            "每餐蛋白质",
            "每餐约 {}–{} 克，每 3–4 小时一次".format(*per_meal_protein(w)),
            f"{_g(w)}×0.25={0.25 * w:.1f}，{_g(w)}×0.40={0.40 * w:.1f}（每餐每公斤体重 0.25–0.40 克），"
            "取整到 5 克、不少于 20 克（每餐 20–40 克）",
            data,
            "K09、K36",
        ),
    ]
    if goal in ("fat_loss", "减脂"):
        out.append(
            Finding(
                "减脂期蛋白质",
                "减脂期可以吃到每公斤去脂体重 2.3–3.1 克；没有体脂数据时按上面每公斤体重 2.0 克的上限来",
                "去脂体重 = 体重 ×（1 − 体脂率），需要体脂数据",
                data,
                "K09、K37",
            )
        )
    return out


def _energy_left(w: float, goal: str | None, kcal: float) -> Finding:
    a, b, _, _ = protein_range(w, goal)
    left_hi, left_lo = kcal - a * 4, kcal - b * 4
    return Finding(
        "留给碳水和脂肪的热量",
        f"每日热量目标 {kcal:.0f} 千卡，蛋白质 {a}–{b} 克约占 {a * 4}–{b * 4} 千卡，"
        f"剩下约 {left_lo:.0f}–{left_hi:.0f} 千卡给碳水和脂肪；碳水最多也只有约 {left_hi / 4:.0f} 克（还要留出脂肪）",
        f"蛋白质和碳水每克约 4 千卡：{kcal:.0f}−{b}×4={left_lo:.0f}，{kcal:.0f}−{a}×4={left_hi:.0f}，{left_hi:.0f}÷4={left_hi / 4:.0f}",
        f"每日热量目标与体重 {_g(w)} 公斤",
        "指标计算（每日热量目标）",
    )


def _carbs(
    w: float, goal: str | None, minutes: int | None, kcal: float | None = None
) -> list[Finding] | str:
    if minutes is None:
        return "碳水要看每天练多久：问一下每天大概练几分钟再算。"
    if goal in ("endurance", "耐力") and minutes >= 60:
        lo, hi, why = 6, 10, "耐力训练（每天 1–3 小时中高强度）"
    elif minutes >= 45:
        lo, hi, why = 5, 7, "中等量训练（每天约 1 小时）"
    else:
        return "每天练不到 45 分钟时，资料里没有按体重的碳水数字，按膳食指南每天谷类 200–300 克（K17）安排即可。"
    out = [
        Finding(
            "每天碳水（按训练量）",
            f"每天约 {lo * w:.0f}–{hi * w:.0f} 克",
            f"{_g(w)}×{lo}={lo * w:.0f}，{_g(w)}×{hi}={hi * w:.0f}（{why}：每公斤体重 {lo}–{hi} 克）",
            f"体重 {_g(w)} 公斤，每天训练约 {minutes} 分钟",
            "K38",
        )
    ]
    if kcal is not None:
        a, _, _, _ = protein_range(w, goal)
        if lo * w * 4 > kcal - a * 4:  # 按训练量的碳水已经超过热量目标能容纳的
            out[0] = Finding(
                out[0].name,
                out[0].text + "，但这超出了他的热量目标能容纳的量，以热量目标为准，不要照这个数给",
                out[0].how,
                out[0].data,
                out[0].source,
            )
        out.append(_energy_left(w, goal, kcal))
    return out


def _supplements(w: float, items: Collection[Item]) -> list[Finding]:
    data = f"体重 {_g(w)} 公斤"
    out = []
    if "creatine" in items:
        out.append(
            Finding(
                "肌酸",
                f"一水肌酸每天 3–5 克；想快点见效可以先冲击 5–7 天，每天约 {0.3 * w:.0f} 克分 4 次",
                f"冲击量 {_g(w)}×0.3={0.3 * w:.1f} 克/天（每公斤体重 0.3 克）；维持量与体重无关",
                data,
                "K10",
            )
        )
    if "caffeine" in items:
        out.append(
            Finding(
                "咖啡因",
                f"运动前约 60 分钟 {3 * w:.0f}–{6 * w:.0f} 毫克；到 {9 * w:.0f} 毫克左右副作用明显增多",
                f"{_g(w)}×3={3 * w:.0f}，{_g(w)}×6={6 * w:.0f}，{_g(w)}×9={9 * w:.0f}（每公斤体重 3–6 毫克，9 毫克副作用多）",
                data,
                "K11",
            )
        )
    if "beta_alanine" in items:
        out.append(
            Finding(
                "β-丙氨酸",
                "每天 4–6 克，分几次吃，至少连续 2–4 周；主要帮助 1–4 分钟的高强度运动；皮肤刺痛时分小剂量",
                "剂量与体重无关",
                data,
                "K43",
            )
        )
    if "hydration" in items:
        out.append(
            Finding(
                "运动前补水",
                f"运动前至少 4 小时慢慢喝 {5 * w:.0f}–{7 * w:.0f} 毫升；运动中失水别让体重掉超过 {0.02 * w:.1f} 公斤",
                f"{_g(w)}×5={5 * w:.0f}，{_g(w)}×7={7 * w:.0f}（每公斤体重 5–7 毫升）；{_g(w)}×2%={0.02 * w:.1f}",
                data,
                "K12",
            )
        )
    return out


def nutrition(
    weight_kg: float | None,
    *,
    goal: str | None = None,
    items: Collection[Item] | None = None,
    training_minutes: int | None = None,
    weight_source: str = "",
    kcal_target: float | None = None,
) -> Result:
    if weight_kg is None:
        return Result.note(
            "没有体重记录，算不出按体重的量：请他记一次体重，或者在问题里说一下体重。"
        )
    if not 25 <= weight_kg <= 300:
        return Result.note("体重要在 25 到 300 公斤之间。")
    w = weight_kg
    default: tuple[Item, ...] = ("protein",)
    chosen: Collection[Item] = items or default
    findings: list[Finding] = []
    notes: list[str] = []
    if weight_source:
        notes.append(f"体重用的是{weight_source}。")
    if "protein" in chosen:
        findings += _protein(w, goal)
    if "carbs" in chosen:
        carbs = _carbs(w, goal, training_minutes, kcal_target)
        if isinstance(carbs, str):
            notes.append(carbs)
            if kcal_target is not None:
                findings.append(_energy_left(w, goal, kcal_target))
        else:
            findings += carbs
    findings += _supplements(w, chosen)
    if {"creatine", "caffeine", "beta_alanine"} & set(chosen):
        notes.append("补剂只说成分和剂量，不推荐品牌；有肾病、心脏病、怀孕或在吃药的，先问医生。")
    return Result(tuple(findings), notes=tuple(notes))
