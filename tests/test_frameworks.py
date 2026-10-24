"""各角色的专业提示词（spec [2026-10-23] §15）：结构完整、只属于本角色、引用的资料都存在且这一轮可以引用。"""

import asyncio
from typing import Any

from ironm_agent.experts import consult
from ironm_agent.frameworks import FRAMEWORKS, framework, framework_refs
from ironm_agent.kb import default_kb
from ironm_agent.llm import Reply
from ironm_agent.roles import EXPERTS, SPECS, Role
from ironm_agent.tools import Toolbox
from tests.fakes import FakeLLM, jsonr, system_of

SECTIONS = (
    "【你的专业身份】",
    "【你的专业思考顺序",
    "【专业判断规则】",
    "【常见错误，别犯】",
    "【答之前自检】",
)


def test_every_role_has_all_sections() -> None:
    for role in EXPERTS:
        text = framework(role)
        for s in SECTIONS:
            assert s in text, (role, s)
        assert "【输出要写全】" in text or "【处方要写全】" in text, role


def test_refs_exist_in_knowledge_base() -> None:
    kb = default_kb()
    for role in (*EXPERTS, Role.GENERAL):
        refs = framework_refs(role)
        assert refs, role
        missing = [r for r in refs if kb.get(r) is None]
        assert not missing, (role, missing)


def test_each_prompt_belongs_to_its_role() -> None:
    assert "持证体能教练" in FRAMEWORKS[Role.TRAINER] and "运动营养师" in FRAMEWORKS[Role.NUTRITION]
    assert "nutrition_calc" not in FRAMEWORKS[Role.TRAINER]
    assert "check_plan" not in FRAMEWORKS[Role.NUTRITION]
    assert "照练、减量、休息、就医" in FRAMEWORKS[Role.RECOVERY]


def test_each_prompt_says_what_it_owns_and_hands_off() -> None:
    """负责什么、不负责什么、转给谁（spec [2026-10-23] §20）。"""
    names = {r: SPECS[r].name for r in EXPERTS}
    for role in EXPERTS:
        text = FRAMEWORKS[role]
        assert "【你负责】" in text and "【你不负责，转给谁】" in text, role
        handoff = text[text.index("【你不负责，转给谁】") : text.index("【你的专业思考顺序")]
        assert all(names[o] in handoff for o in EXPERTS if o is not role), role
    # 数据归各自领域解读
    assert "体重" in FRAMEWORKS[Role.NUTRITION].split("【你不负责")[0]
    assert "心率变异性" in FRAMEWORKS[Role.RECOVERY].split("【你不负责")[0]
    assert "步数" in FRAMEWORKS[Role.TRAINER].split("【你不负责")[0]
    # 伤痛交给康复恢复师
    assert "康复恢复师" in FRAMEWORKS[Role.TRAINER] and "pain_check" not in FRAMEWORKS[Role.TRAINER]


def scripted(*replies: Reply) -> Any:
    it = iter(replies)
    return lambda *_: next(it)


def test_copying_a_rule_from_the_prompt_passes_the_check() -> None:
    tb = Toolbox(SPECS[Role.TRAINER], kb=default_kb(), health=None, user_id="42", session_id="s")
    llm = FakeLLM(
        scripted(jsonr({"conclusion": "大动作组间休息 2–3 分钟〔K03〕，每周 10 组及以上〔K04〕"}))
    )
    c = asyncio.run(consult(SPECS[Role.TRAINER], "组间休息多久", [], (), tb, llm))
    assert (
        "〔K03〕" in c.opinion.conclusion and "〔K04〕" in c.opinion.conclusion
    )  # 没有被改标〔经验〕
    assert {"K03", "K04"} <= set(tb.evidence.entries)


def test_shared_rules_in_every_prompt() -> None:
    for role in EXPERTS:
        tb = Toolbox(SPECS[role], kb=default_kb(), health=None, user_id="42", session_id="s")
        llm = FakeLLM(scripted(jsonr({"conclusion": "好的"})))
        asyncio.run(consult(SPECS[role], "问题", [], (), tb, llm))
        system = system_of(llm.seen[0][1])
        assert "先给结论，再用一句话说理由" in system
        assert "只照档案、数据和他这句话说" in system
        assert "【你的专业身份】" in system
