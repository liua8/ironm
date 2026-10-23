"""估算最大重量（1RM）与按"目标次数 + 还剩几次"推重量。"""

from __future__ import annotations

import math

from ironm_agent.protools.result import Finding, Result

MAX_REPS = 12  # 次数再多，公式估得就很不准了
MAX_RIR = 4
SOURCE_1RM = "Epley（1985）与 Brzycki（1993）的估算公式；次数越多估得越不准"
SOURCE_LOAD = "Epley 公式倒推；还剩几次与 RPE 的对应：RPE = 10 − 还剩次数（K28）"


def _g(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".")


def epley(weight: float, reps: int) -> float:
    return weight if reps == 1 else weight * (1 + reps / 30)


def brzycki(weight: float, reps: int) -> float:
    return weight * 36 / (37 - reps)


def _check(weight: float, reps: int) -> str:
    if not 0 < weight <= 500:
        return "重量要在 0 到 500 公斤之间。"
    if not 1 <= reps <= MAX_REPS:
        return f"次数要在 1 到 {MAX_REPS} 次之间；次数再多，公式估得不准，换一组较重、做 3–10 次的来估。"
    return ""


def one_rep_max(weight: float, reps: int) -> Result:
    if problem := _check(weight, reps):
        return Result.note(problem)
    e, b = epley(weight, reps), brzycki(weight, reps)
    text = f"{_g(weight)} 公斤做 {reps} 次，估算最大重量约 {e:.0f} 公斤（Epley）、{b:.0f} 公斤（Brzycki）"
    how = f"Epley：{_g(weight)}×(1+{reps}/30)={e:.1f}；Brzycki：{_g(weight)}×36÷(37−{reps})={b:.1f}"
    if reps == 1:
        text = f"{_g(weight)} 公斤做 1 次，这就是最大重量"
        how = "做 1 次的重量就是最大重量"
    return Result(
        (Finding("估算最大重量", text, how, f"这一组：{_g(weight)} 公斤 × {reps} 次", SOURCE_1RM),),
        notes=("估算只作参考：没练到力竭的组会低估；新手的估算误差更大。",),
    )


def load_for(
    target_reps: int,
    rir: int,
    *,
    max_kg: float | None = None,
    weight: float | None = None,
    reps: int | None = None,
    step: float = 2.5,
) -> Result:
    """推重量：最大重量直接给出，或由一组的重量和次数先估出来；结果向下取到 step 的整数倍（偏保守）。"""
    if not 1 <= target_reps <= MAX_REPS:
        return Result.note(f"目标次数要在 1 到 {MAX_REPS} 次之间。")
    if not 0 <= rir <= MAX_RIR:
        return Result.note(f"还剩几次要在 0 到 {MAX_RIR} 次之间。")
    if target_reps + rir > MAX_REPS:
        return Result.note(
            f"目标次数加上还剩几次超过 {MAX_REPS} 次，公式推不准，按感觉选重量更合适。"
        )
    if not 0 < step <= 10:
        return Result.note("重量的最小档位要在 0 到 10 公斤之间。")
    data = []
    if max_kg is None:
        if weight is None or reps is None:
            return Result.note("需要最大重量，或者最近一组的重量和次数。")
        if problem := _check(weight, reps):
            return Result.note(problem)
        max_kg = epley(weight, reps)
        data.append(
            f"最近一组 {_g(weight)} 公斤 × {reps} 次，按 Epley 估算最大重量 {max_kg:.1f} 公斤"
        )
    elif not 0 < max_kg <= 500:
        return Result.note("最大重量要在 0 到 500 公斤之间。")
    else:
        data.append(f"最大重量 {_g(max_kg)} 公斤")
    total = target_reps + rir
    raw = max_kg / (1 + total / 30)
    load = math.floor(raw / step) * step
    pct = load / max_kg * 100
    text = (
        f"目标 {target_reps} 次、还剩 {rir} 次（RPE {10 - rir}），建议重量约 {_g(load)} 公斤"
        f"（约为最大重量的 {pct:.0f}%）"
    )
    how = (
        f"把这组能做的总次数当作 {target_reps}+{rir}={total} 次，按 Epley 倒推："
        f"{max_kg:.1f}÷(1+{total}/30)={raw:.1f}，向下取到 {_g(step)} 公斤的整数倍"
    )
    return Result(
        (Finding("建议重量", text, how, "；".join(data), SOURCE_LOAD),),
        notes=("第一组按这个重量做，实际还剩的次数和目标差得多时，下一组再加减。",),
    )
