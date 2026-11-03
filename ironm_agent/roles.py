"""领域和管家：训练、饮食、恢复现在是规程和资料的领域标签（10-28 起只有一个管家 GENERAL 作答）。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    TRAINER = "trainer"
    NUTRITION = "nutrition"
    RECOVERY = "recovery"
    GENERAL = "general"  # 管家：10-28 起唯一作答的那一位


@dataclass(frozen=True)
class RoleSpec:
    role: Role
    name: str  # 给用户看的中文名
    duty: str  # 负责回答哪类问题
    kb_domains: frozenset[str]  # 能查的依据库领域
    health_data: bool  # 能否查这个人的健康数据


# 三个大领域（spec [2026-10-23] §20）：现在是规程和资料的领域标签，决定装哪份基础规程、能查哪些资料
SPECS: dict[Role, RoleSpec] = {
    Role.TRAINER: RoleSpec(
        Role.TRAINER,
        "训练教练",
        "怎么练：训练计划（频率、组数次数、强度、有氧与力量、进阶与减量、平台期）、动作做法与要点、"
        "替代动作、热身、坚持训练；步数、力量进步等训练数据的解读",
        frozenset({"training", "exercise", "safety", "data"}),
        True,
    ),
    Role.NUTRITION: RoleSpec(
        Role.NUTRITION,
        "营养师",
        "怎么吃：饮食原则、热量、蛋白质、补剂、减脂与增肌饮食、外卖外食、喝水、坚持饮食；"
        "体重、体脂等身体成分数据的解读；饮食与补剂的风险",
        frozenset({"nutrition", "safety", "data"}),
        True,
    ),
    Role.RECOVERY: RoleSpec(
        Role.RECOVERY,
        "康复恢复师",
        "身体状态：伤痛与带伤训练、伤后回归、动作引起的疼痛、睡眠、疲劳、肌肉酸痛、生病时的安排、"
        "过度训练；睡眠、心率、心率变异性、血压和化验、体检指标的解读，以及什么情况要就医",
        frozenset({"recovery", "safety", "data"}),
        True,
    ),
}

EXPERTS: tuple[Role, ...] = tuple(SPECS)
COACH_NAME = "管家"

# 管家（单 Agent，10-28）：用全部工具和资料一次作答
GENERAL = RoleSpec(
    Role.GENERAL,
    "全能教练",
    "训练安排、动作做法、饮食营养、恢复与睡眠、身体数据的解读，以及相关的风险与就医提醒",
    frozenset({"training", "exercise", "nutrition", "recovery", "safety", "data"}),
    True,
)


def spec_of(role: Role) -> RoleSpec:
    return GENERAL if role is Role.GENERAL else SPECS[role]
