"""Agent 的角色：职责、能用的工具与资料、调度用的关键词。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    COACH = "coach"
    PLANNER = "planner"
    EXERCISE = "exercise"
    NUTRITION = "nutrition"
    RECOVERY = "recovery"
    DATA = "data"
    SAFETY = "safety"


@dataclass(frozen=True)
class RoleSpec:
    role: Role
    name: str  # 给用户看的中文名
    duty: str  # 负责回答哪类问题
    kb_domains: frozenset[str]  # 能查的依据库领域
    health_data: bool  # 能否查这个人的健康数据
    keywords: tuple[str, ...]  # 模型不可用时按关键词调度


SPECS: dict[Role, RoleSpec] = {
    Role.PLANNER: RoleSpec(
        Role.PLANNER,
        "训练规划",
        "训练频率、组数次数、强度、有氧与力量的安排、进阶与减量",
        frozenset({"training"}),
        False,
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
        ),
    ),
    Role.EXERCISE: RoleSpec(
        Role.EXERCISE,
        "动作教练",
        "动作做法与要点、常见错误、替代动作、热身",
        frozenset({"exercise", "training"}),
        False,
        (
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
        ),
    ),
    Role.NUTRITION: RoleSpec(
        Role.NUTRITION,
        "营养",
        "饮食原则、热量、蛋白质、补剂、减脂与增肌饮食、喝水",
        frozenset({"nutrition"}),
        False,
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
        ),
    ),
    Role.RECOVERY: RoleSpec(
        Role.RECOVERY,
        "恢复",
        "睡眠、疲劳、肌肉酸痛、休息安排、心率变异性等恢复指标",
        frozenset({"recovery"}),
        True,
        ("睡", "失眠", "累", "疲劳", "酸痛", "恢复", "休息", "心率变异", "hrv", "过度训练"),
    ),
    Role.DATA: RoleSpec(
        Role.DATA,
        "数据分析",
        "体重、心率、步数、血压、睡眠时长等指标的趋势与解读",
        frozenset({"data"}),
        True,
        ("体重", "心率", "步数", "血压", "趋势", "数据", "指标", "最近", "变化", "体脂", "化验"),
    ),
    Role.SAFETY: RoleSpec(
        Role.SAFETY,
        "安全官",
        "运动与饮食里的安全风险、身体不适、特殊人群、什么情况要就医；只提醒和设限",
        frozenset({"safety"}),
        False,
        ("疼", "痛", "不舒服", "受伤", "怀孕", "高血压", "糖尿病", "心脏", "头晕", "安全"),
    ),
}

EXPERTS: tuple[Role, ...] = tuple(SPECS)
COACH_NAME = "主教练"


def name_of(role: Role) -> str:
    return COACH_NAME if role is Role.COACH else SPECS[role].name
