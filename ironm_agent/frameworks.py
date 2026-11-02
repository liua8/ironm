"""管家的专业提示词（spec [2026-10-23] §12、§15、§87）。

几个专业（训练、动作、饮食、恢复、数据）的要点合在一起；判断规则里的数字都写明依据库编号（〔K..〕），
这些条目会记为这一轮可以引用的依据。少见情况的规则随基础规程装进去（skills.yaml 的 special，§74）。
"""

from __future__ import annotations

import re
from collections.abc import Collection

from ironm_agent.roles import Role

# 管家的专业提示词：每轮都带，只写身份、各领域的分工和工具、答前自检；具体数字在规程里（§88）
FRAMEWORKS: dict[Role, str] = {}
FRAMEWORKS[
    Role.GENERAL
] = """【你的专业身份】你同时是训练教练、运动营养师和康复恢复师：先判断他问的属于哪一类，再按那个专业的标准回答。具体做法和数字在这一轮装上的规程里（各领域的基础规程和专门规程），照着用；规程没写到的按专业常识答，说不出出处的数字不写。

【各领域管什么、用什么工具】
- 训练：计划、组次和强度、进阶和减量、有氧；写好或改好的计划先用 check_plan 检查，具体重量用 estimate_strength。
- 动作：做法、要点、换动作；查动作库用 search_exercises，换动作用 find_substitutes。
- 饮食：热量、蛋白质、吃法、补剂；按体重算的量用 nutrition_calc。
- 恢复：酸痛、伤痛、生病、睡眠、疲劳；疼痛用 pain_check，有就医信号先说就医。
- 数据：体重、心率、睡眠、步数、化验；变化用 trend_analysis，分清波动和真实变化；没问建议就不给建议。
- 资料：先查知识库；查不到合适的、又需要具体的数或结论时，有 search_web 就联网查权威机构，查不到如实说，不编。

【答之前自检】回答用到他的情况了吗？给的量具体吗？伤病和安全照顾到了吗？每个数字都有出处吗？"""

_REF = re.compile(r"〔(K\d{2,4})〕")


def framework(role: Role, flags: Collection[str] = ()) -> str:
    """管家的专业提示词。少见情况的规则（flags）随规程装进去（skills 的 special），这里不再按角色拼。"""
    return FRAMEWORKS.get(role, "")


def framework_refs(role: Role, flags: Collection[str] = ()) -> tuple[str, ...]:
    """提示词里引用到的依据库编号：这些条目记为这一轮可以引用的依据。"""
    return tuple(dict.fromkeys(_REF.findall(framework(role, flags))))


def flags_of(risks: Collection[str], injured: bool, readiness: str = "") -> frozenset[str]:
    """档案里的风险和伤病 → 要加进提示词的少见情况。"""
    keys = set(risks)
    out = set()
    if keys & {"bp_crisis", "bp_high", "hypertension"}:
        out.add("bp")
    for k in ("pregnancy", "diabetes"):
        if k in keys:
            out.add(k)
    if keys & {"cardiac", "surgery"}:
        out.add("cardiac")
    if injured:
        out.add("injury")
    if readiness == "poor":
        out.add("poor")
    return frozenset(out)
