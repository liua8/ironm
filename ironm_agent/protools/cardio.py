"""有氧按热量算时长（spec [2026-11-06] §193）：选哪种有氧、每周（或每次）想多消耗多少千卡，按代谢当量 × 体重算每次、每周练多久。

用净代谢当量（减去坐着本来就有的 1 个代谢当量）：说的是"比不练多消耗多少"。数值来自 2024 版成人体力活动纲要
（依据 K117），是一般人的平均值，个人差异大，只当估算；不加进饮食页的"还能吃"（每日总消耗已经算了活动量）。
"""

from __future__ import annotations

from typing import Literal

from ironm_agent.protools.result import Finding, Result

type Kind = Literal["walk", "jog", "bike", "elliptical", "row", "rope"]
# 动作库里的名字、中等强度的代谢当量、怎么算中等
KINDS: dict[str, tuple[str, float, str]] = {
    "walk": ("快走", 4.3, "每小时约 5.6 公里"),
    "jog": ("跑步机慢跑", 8.3, "每小时约 8 公里"),
    "bike": ("骑行（动感单车）", 7.0, "中等用力"),
    "elliptical": ("椭圆机", 5.0, "中等用力"),
    "row": ("划船机", 7.0, "中等用力"),
    "rope": ("跳绳", 11.8, "每分钟 100–120 下"),
}
SOURCE = "K117（2024 版成人体力活动纲要的代谢当量）"
MAX_SESSION = 90  # 一次超过这么多分钟就建议多分几次


def _five(x: float) -> int:
    return max(5, round(x / 5) * 5)


def cardio(weight: float | None, kind: str, *, weekly_kcal: float | None = None, session_kcal: float | None = None,
           sessions: int | None = None, minutes: float | None = None) -> Result:  # fmt: skip
    """weekly_kcal 每周想多消耗多少（配 sessions 每周几次）；或 session_kcal 每次多少；或 minutes 反过来算一次消耗多少。"""
    if kind not in KINDS:
        return Result.note(f"有氧种类写 {'、'.join(KINDS)} 之一。")
    if not weight or weight <= 0:
        return Result.note("还没有体重记录，算不了消耗：请他先记一次体重。")
    name, met, pace = KINDS[kind]
    per_min = (met - 1) * weight / 60  # 每分钟比坐着多消耗多少千卡
    data = f"体重 {weight:g} 公斤；{name}（{pace}）{met:g} 个代谢当量"
    how_base = f"（{met:g}−1）×{weight:g}÷60≈{per_min:.1f} 千卡/分钟"
    if minutes:
        kcal = per_min * minutes
        return Result((Finding("一次消耗", f"{name} {minutes:g} 分钟约多消耗 {round(kcal / 10) * 10} 千卡（估算）",
                               f"{how_base}，×{minutes:g} 分钟", data, SOURCE),),
                      notes=_notes(name), entries=("K117",))  # fmt: skip
    n = sessions or 3
    if weekly_kcal:
        each = weekly_kcal / n
    elif session_kcal:
        each, weekly_kcal = session_kcal, session_kcal * n
    else:
        return Result.note("写每周想多消耗多少（weekly_kcal，配 sessions 每周几次）或每次多少（session_kcal），或者写 minutes。")
    mins = _five(each / per_min)
    findings = [Finding("每次练多久", f"{name}每次约 {mins} 分钟，约多消耗 {round(each / 10) * 10} 千卡（估算）",
                        f"{how_base}，{each:.0f}÷{per_min:.1f}≈{each / per_min:.0f} 分钟，取整到 5 分钟", data, SOURCE),
                Finding("每周", f"每周 {n} 次、一共约 {mins * n} 分钟，约多消耗 {round(weekly_kcal / 10) * 10} 千卡（估算）",
                        f"{mins}×{n}", data, SOURCE)]  # fmt: skip
    notes = list(_notes(name))
    if mins > MAX_SESSION:
        notes.insert(0, f"一次要 {mins} 分钟，太长：多分几次、换消耗高一点的有氧，或者把目标调小。")
    return Result(tuple(findings), notes=tuple(notes), entries=("K117",))


def _notes(name: str) -> tuple[str, ...]:
    return (
        f"写进计划时：动作写「{name}」，reps 写分钟数（如「30 分钟」），note 写「约多少千卡（估算）」；计划检查会把分钟算进这次的时长。",
        "是按一般人平均算的，个人差异大；不加进饮食页的「还能吃」，手表上的消耗也不准，别拿来加餐。",
        "膝、踝有伤的不排跑步和跳绳，换骑行、椭圆机或快走。",
    )
