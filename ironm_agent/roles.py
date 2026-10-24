"""Agent 的角色：职责、能用的工具与资料、调度用的关键词。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    COACH = "coach"
    TRAINER = "trainer"
    NUTRITION = "nutrition"
    RECOVERY = "recovery"
    GENERAL = "general"  # 单 Agent 对照组的"全能教练"，不参加调度


@dataclass(frozen=True)
class RoleSpec:
    role: Role
    name: str  # 给用户看的中文名
    duty: str  # 负责回答哪类问题
    kb_domains: frozenset[str]  # 能查的依据库领域
    health_data: bool  # 能否查这个人的健康数据
    keywords: tuple[str, ...]  # 模型不可用时按关键词调度


# 专业 Agent 按大领域分三个，小领域做成 Skill（spec [2026-10-23] §20）
SPECS: dict[Role, RoleSpec] = {
    Role.TRAINER: RoleSpec(
        Role.TRAINER,
        "训练教练",
        "怎么练：训练计划（频率、组数次数、强度、有氧与力量、进阶与减量、平台期）、动作做法与要点、"
        "替代动作、热身、坚持训练；步数、力量进步等训练数据的解读",
        frozenset({"training", "exercise", "safety", "data"}),
        True,
        (
            "计划",
            "安排",
            "组",
            "次数",
            "频率",
            "强度",
            "增肌",
            "力量",
            "有氧",
            "跑步",
            "减量",
            "一周练",
            "练几次",
            "多久练",
            "平台期",
            "训练量",
            "动作",
            "深蹲",
            "硬拉",
            "卧推",
            "引体",
            "俯卧撑",
            "平板",
            "姿势",
            "发力",
            "替代",
            "热身",
            "拉伸",
            "划船",
            "弓步",
            "步数",
            "坚持",
        ),
    ),
    Role.NUTRITION: RoleSpec(
        Role.NUTRITION,
        "营养师",
        "怎么吃：饮食原则、热量、蛋白质、补剂、减脂与增肌饮食、外卖外食、喝水、坚持饮食；"
        "体重、体脂等身体成分数据的解读；饮食与补剂的风险",
        frozenset({"nutrition", "safety", "data"}),
        True,
        (
            "吃",
            "饮食",
            "热量",
            "卡路里",
            "蛋白",
            "碳水",
            "脂肪",
            "肌酸",
            "咖啡",
            "补剂",
            "减脂",
            "喝水",
            "饿",
            "早餐",
            "晚餐",
            "外卖",
            "体重",
            "体脂",
        ),
    ),
    Role.RECOVERY: RoleSpec(
        Role.RECOVERY,
        "康复恢复师",
        "身体状态：伤痛与带伤训练、伤后回归、动作引起的疼痛、睡眠、疲劳、肌肉酸痛、生病时的安排、"
        "过度训练；睡眠、心率、心率变异性、血压等指标的解读，以及什么情况要就医",
        frozenset({"recovery", "safety", "data"}),
        True,
        (
            "睡",
            "失眠",
            "累",
            "疲劳",
            "酸痛",
            "恢复",
            "休息",
            "心率",
            "hrv",
            "过度训练",
            "疼",
            "痛",
            "不舒服",
            "受伤",
            "扭",
            "肿",
            "头晕",
            "感冒",
            "发烧",
            "生病",
            "血压",
            "化验",
        ),
    ),
}

EXPERTS: tuple[Role, ...] = tuple(SPECS)
COACH_NAME = "管家"

# 单 Agent 对照组（spec [2026-10-23] §1）：一位"全能教练"用全部工具和资料一次作答，不调度、不整合
GENERAL = RoleSpec(
    Role.GENERAL,
    "全能教练",
    "训练安排、动作做法、饮食营养、恢复与睡眠、身体数据的解读，以及相关的风险与就医提醒",
    frozenset({"training", "exercise", "nutrition", "recovery", "safety", "data"}),
    True,
    (),
)


def spec_of(role: Role) -> RoleSpec:
    return GENERAL if role is Role.GENERAL else SPECS[role]


def name_of(role: Role) -> str:
    return COACH_NAME if role is Role.COACH else spec_of(role).name
