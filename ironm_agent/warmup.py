"""计划页的热身和估算消耗（spec [2026-10-23] §116）：由代码按这天的动作生成，不调用模型。

热身不写成计划里的动作，不算组数，不进训练记录；估算消耗只在计划页显示，不加进饮食页的"还能吃"
（每日总消耗已经按活动系数算了活动量）。
"""

from __future__ import annotations

from dataclasses import dataclass

from ironm_agent.protools.movement import COMPOUND, Move, find
from ironm_agent.training import Session

EASY_MIN, LOOSEN_MIN, RAMP_MIN = 5, 2, 2  # 全身低强度、活动部位、热身组各约几分钟
MET_LOW, MET_HIGH = 3.5, 6.0  # 力量训练 02054 / 02050〔K117〕

_LOWER = frozenset({"squat", "hinge", "lunge", "bridge", "calf", "abduction"})
_PUSH = frozenset({"h_push", "v_push", "shoulder", "extension"})
_PULL = frozenset({"h_pull", "v_pull", "curl"})
# 页面上给的出处（K06 美国运动医学会：训练前 5–10 分钟低到中等强度热身；K61：只做针对动作的热身组）
BASIS = "热身 5–10 分钟按美国运动医学会的建议；大动作前做几组轻重量是省时训练综述的做法；活动部位是教练经验"
_EASY = frozenset({"cardio", "stretch"})  # 只有这些的一天：只写全身低强度
_LOOSEN = (
    (_LOWER, "徒手深蹲、弓步各 8 次，髋绕环每边 5 圈"),
    (_PUSH, "手臂绕环、肩胛前伸后缩各 10 次"),
    (_PULL, "肩胛下沉后缩、猫牛式各 10 次"),
)


@dataclass(frozen=True)
class Warmup:
    minutes: int
    steps: tuple[str, ...]
    basis: str  # 页面上的出处说明（不写编号）


@dataclass(frozen=True)
class Burn:
    low: int
    high: int
    how: str


def warmup(session: Session) -> Warmup:
    """三步：全身低强度、活动开要练的部位、第一个多关节动作的热身组；按这天的动作取舍。"""
    found = [(it, m) for it in session.items if (m := find(it.exercise)) is not None]
    patterns = {m.tag.pattern for _, m in found}
    if patterns and patterns <= _EASY:
        return Warmup(EASY_MIN, ("从慢速开始 5 分钟，到微微出汗、还能说整句话",), BASIS)
    machine = any("器械" in m.exercise.equipment for _, m in found)
    how = "骑单车、椭圆机或快走" if machine else "原地踏步、开合跳或快走"
    steps = [f"全身低强度 5 分钟：{how}，到微微出汗、还能说整句话"]
    loosen = [line for kinds, line in _LOOSEN if patterns & kinds]
    if loosen:
        steps.append("活动开要练的部位：" + "；".join(loosen))
    first = next(((it.exercise, m) for it, m in found if m.tag.pattern in COMPOUND), None)
    if first is not None:  # 用计划里写的名字（动作库里可能是另一种叫法）
        steps.append(_ramp(*first))
    return Warmup(
        EASY_MIN + LOOSEN_MIN * bool(loosen) + RAMP_MIN * (first is not None), tuple(steps), BASIS
    )


def _ramp(name: str, m: Move) -> str:
    if set(m.exercise.equipment) <= {"自重"}:
        return f"{name}先做 1 组，次数减半"
    return f"{name}先做 2 组热身：正式重量的一半做 8 次、七成做 3–5 次"


def burn(minutes: int, weight_kg: float | None) -> Burn | None:
    """估算这一次的消耗：代谢当量 3.5–6.0 × 体重 × 小时，两头取整到 10；没有体重时不估。"""
    if not weight_kg or weight_kg <= 0 or minutes <= 0:
        return None
    lo, hi = (round(met * weight_kg * minutes / 60 / 10) * 10 for met in (MET_LOW, MET_HIGH))
    how = (
        f"按力量训练的代谢当量 {MET_LOW:.1f}（多个动作、每组 8–15 次）到 {MET_HIGH:.1f}（用力程度高）"
        f"× 体重 {weight_kg:g} 公斤 × {minutes} 分钟估算（2024 版成人体力活动纲要）；是一般人的平均值，个人差异大。"
        "不加进饮食页的「还能吃」：每日总消耗已经算了活动量。"
    )
    return Burn(lo, hi, how)
