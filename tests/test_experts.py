"""专业 Agent：查依据、按依据作答、编号与数字核对、工具权限。"""

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

from ironm_agent.experts import consult
from ironm_agent.kb import default_kb
from ironm_agent.llm import Reply, Stage
from ironm_agent.roles import SPECS, Role
from ironm_agent.tools import HEALTH, KNOWLEDGE, Toolbox
from tests.fakes import FakeHealth, FakeLLM, call, jsonr, tool_results


def box(role: Role, health: FakeHealth | None = None) -> Toolbox:
    return Toolbox(SPECS[role], kb=default_kb(), health=health, user_id="42", session_id="42:s1")


def run(role: Role, handler: Any, health: FakeHealth | None = None, text: str = "问题") -> Any:
    tb = box(role, health)
    return asyncio.run(consult(SPECS[role], text, [], (), tb, FakeLLM(handler))), tb


def scripted(*replies: Reply) -> Any:
    it = iter(replies)
    return lambda *_: next(it)


def test_nutrition_cites_knowledge_and_numbers_from_it() -> None:
    c, _ = run(
        Role.NUTRITION,
        scripted(
            call(KNOWLEDGE, query="肌酸"),
            jsonr(
                {
                    "speak": True,
                    "conclusion": "每天 3–5 克一水肌酸即可〔K10〕",
                    "how": "长期吃",
                }
            ),
        ),
    )
    assert c.status == "spoke" and c.opinion.basis == ("K10",) and "K10" in c.evidence.entries


def test_wrongly_sourced_number_is_relabelled_as_experience_not_silenced() -> None:
    bad = jsonr({"speak": True, "conclusion": "每天吃 25 克〔K10〕"})
    c, _ = run(Role.NUTRITION, scripted(call(KNOWLEDGE, query="肌酸"), bad, bad))
    assert c.status == "spoke"
    assert c.opinion.conclusion == "每天吃 25 克〔经验〕" and "K10" not in c.opinion.basis


def test_number_must_come_from_cited_entry_not_just_seen_one() -> None:
    # "20" 在同时查到的 K09（蛋白质每餐 20–40 克）里，但意见只引用了 K10（肌酸）
    bad = jsonr({"speak": True, "conclusion": "肌酸每天吃 20 克〔K10〕"})
    good = jsonr({"speak": True, "conclusion": "肌酸每天 3–5 克〔K10〕"})
    c, tb = run(Role.NUTRITION, scripted(call(KNOWLEDGE, query="肌酸 蛋白质"), bad, good))
    assert "K09" in tb.evidence.entries and c.status == "spoke" and "3–5" in c.opinion.conclusion


def test_made_up_basis_id_becomes_experience() -> None:
    fake = jsonr({"speak": True, "conclusion": "每晚睡够 7 小时〔K99〕"})
    c, _ = run(Role.RECOVERY, scripted(fake, fake))
    assert c.status == "spoke" and c.opinion.conclusion == "每晚睡够 7 小时〔经验〕"


def test_no_evidence_still_answers_from_experience() -> None:
    answer = jsonr(
        {"conclusion": "先把动作做标准，再慢慢加重量〔经验〕", "how": "每次只加一点〔经验〕"}
    )
    c, _ = run(Role.EXERCISE, scripted(call(KNOWLEDGE, query="壶铃摇摆"), answer))
    assert c.status == "spoke" and "〔经验〕" in c.opinion.conclusion


def test_model_saying_it_wont_speak_is_not_accepted() -> None:
    silent = jsonr({"speak": False, "reason": "没有依据"})
    answer = jsonr({"conclusion": "可以练，注意循序渐进〔经验〕"})
    c, _ = run(Role.PLANNER, scripted(silent, answer))
    assert c.status == "spoke" and "循序渐进" in c.opinion.conclusion


def test_data_numbers_come_from_health_rows() -> None:
    health = FakeHealth()
    c, tb = run(
        Role.DATA,
        scripted(
            call(HEALTH, indicators=["restingHeartRates"], view="stats"),
            jsonr(
                {
                    "speak": True,
                    "conclusion": "<statement>近 30 天静息心率平均 58 次/分<cite>[r1]</cite></statement>",
                }
            ),
        ),
        health,
    )
    assert c.status == "spoke" and tb.evidence.support["r1"] and c.opinion.basis == ("r1",)
    assert health.asked[0]["user_info"] == {"user_id": "42", "session_id": "42:s1"}


def test_planner_cannot_read_health_data() -> None:
    health = FakeHealth()
    seen: list[str] = []

    def handler(stage: Stage, messages: Sequence[Mapping[str, Any]], has_tools: bool) -> Reply:
        results = tool_results(messages)
        if not results:
            return call(HEALTH, view="stats")
        seen.extend(results)
        return jsonr({"conclusion": "按每周安排来练〔经验〕"})

    c, _ = run(Role.PLANNER, handler, health)
    assert health.asked == [] and "不能使用" in seen[0]
    assert c.status == "spoke"


def test_health_query_failure_is_reported_not_raised() -> None:
    health = FakeHealth(fail=True)
    c, tb = run(
        Role.RECOVERY,
        scripted(
            call(HEALTH, view="stats"), jsonr({"speak": True, "conclusion": "这次没读到你的数据"})
        ),
        health,
    )
    assert tb.evidence.health_failed and c.status == "spoke"


def test_query_limit_is_enforced() -> None:
    def handler(stage: Stage, messages: Sequence[Mapping[str, Any]], has_tools: bool) -> Reply:
        return call(KNOWLEDGE, query="睡眠")

    c, tb = run(Role.RECOVERY, handler)
    assert tb.evidence.knowledge_queries == 3 and c.status == "silent"
