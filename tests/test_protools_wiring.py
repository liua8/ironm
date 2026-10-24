"""专业工具接进作答链路（spec [2026-10-23] §12）：只给对应角色、结果带编号、能通过核对、各角色有自己的思考框架。"""

import asyncio
from datetime import date
from typing import Any

from ironm_agent.experts import consult
from ironm_agent.kb import default_kb
from ironm_agent.llm import Reply, ToolCall
from ironm_agent.metrics import Readings
from ironm_agent.protools.registry import ToolContext
from ironm_agent.roles import EXPERTS, SPECS, Role
from ironm_agent.tools import Toolbox
from tests.fakes import FakeLLM, call, jsonr, system_of, tool_results

TODAY = date(2026, 10, 23)


def ctx(**kw: Any) -> ToolContext:
    base: dict[str, Any] = {
        "goal": "muscle",
        "weight_kg": 70.0,
        "readings": Readings(weight=tuple((date(2026, 10, d), 70.0) for d in range(1, 23))),
        "injured": [],
        "equipment_said": [],
    }
    return ToolContext.build(TODAY, **(base | kw))


def box(role: Role, context: ToolContext | None = None) -> Toolbox:
    return Toolbox(
        SPECS[role],
        kb=default_kb(),
        health=None,
        user_id="42",
        session_id="42:s1",
        context=context or ctx(),
    )


def scripted(*replies: Reply) -> Any:
    it = iter(replies)
    return lambda *_: next(it)


def names(tb: Toolbox) -> set[str]:
    return {s["function"]["name"] for s in tb.schemas()}


def test_each_role_sees_only_its_pro_tools() -> None:
    assert {"check_plan", "estimate_strength"} <= names(box(Role.TRAINER))
    assert "nutrition_calc" not in names(box(Role.TRAINER))
    assert "nutrition_calc" in names(box(Role.NUTRITION)) and "check_plan" not in names(
        box(Role.NUTRITION)
    )
    assert all("trend_analysis" in names(box(r)) for r in EXPERTS)  # 数据归各自领域解读
    assert "pain_check" in names(box(Role.RECOVERY)) and "pain_check" not in names(
        box(Role.TRAINER)
    )
    no_ctx = Toolbox(
        SPECS[Role.TRAINER], kb=default_kb(), health=None, user_id="42", session_id="s"
    )
    assert "check_plan" not in names(no_ctx)  # 没有这个人的情况时不提供专业工具


def test_other_roles_tool_is_refused() -> None:
    tb = box(Role.NUTRITION)
    out = asyncio.run(tb.run(ToolCall("x", "check_plan", {"plan": {}})))
    assert "不能使用这个工具" in out and tb.evidence.pro_queries == 0


def test_tool_result_is_cited_and_passes_checks() -> None:
    tb = box(Role.NUTRITION)
    llm = FakeLLM(
        scripted(
            call("nutrition_calc", items=["protein"]),
            jsonr(
                {
                    "conclusion": "按你的体重，每天吃 112–140 克蛋白质〔C52〕",
                    "how": "每餐 18–28 克〔C53〕",
                }
            ),
        )
    )
    c = asyncio.run(consult(SPECS[Role.NUTRITION], "我每天该吃多少蛋白质", [], (), tb, llm))
    assert c.status == "spoke"
    assert (
        "112–140" in c.opinion.conclusion and "〔C52〕" in c.opinion.conclusion
    )  # 没被改标〔经验〕
    assert "C52" in tb.evidence.calcs and "K09" in tb.evidence.calcs["C52"]
    assert tb.evidence.pro_queries == 1 and tb.evidence.queries == 0  # 不占查询次数
    assert any("[C52]" in r for r in tool_results(llm.seen[-1][1]))


def test_number_not_in_tool_result_is_not_accepted() -> None:
    tb = box(Role.NUTRITION)
    bad = jsonr({"conclusion": "每天吃 200 克蛋白质〔C52〕"})
    llm = FakeLLM(scripted(call("nutrition_calc", items=["protein"]), bad, bad))
    c = asyncio.run(consult(SPECS[Role.NUTRITION], "蛋白质", [], (), tb, llm))
    assert "〔C52〕" not in c.opinion.conclusion  # 对不上的数字不能挂着工具的编号


def test_substitutes_adopt_library_entries_for_citation() -> None:
    tb = box(Role.RECOVERY, ctx(injured=["knee"], equipment_said=["家里有哑铃"]))
    out = asyncio.run(tb.run(ToolCall("x", "find_substitutes", {"exercise": "杠铃深蹲"})))
    assert "箱式深蹲" in out
    assert any(e.title == "箱式深蹲" for e in tb.evidence.entries.values())


def test_prompt_has_own_framework_only() -> None:
    for role in EXPERTS:
        tb = box(role)
        llm = FakeLLM(scripted(jsonr({"conclusion": "好的"})))
        asyncio.run(consult(SPECS[role], "问题", [], (), tb, llm))
        system = system_of(llm.seen[0][1])
        assert f"你的专业思考顺序（{SPECS[role].name}）" in system
        others = [SPECS[r].name for r in EXPERTS if r is not role]
        assert not any(f"你的专业思考顺序（{n}）" in system for n in others)
        assert "专业工具" in system


def test_tool_numbers_show_in_sources() -> None:
    from ironm_agent.compose import solo
    from ironm_agent.render import sources_text

    tb = box(Role.NUTRITION)
    llm = FakeLLM(
        scripted(
            call("nutrition_calc", items=["protein"]),
            jsonr(
                {"answer": "按你的体重，每天吃 112–140 克蛋白质〔C52〕，分到每餐 18–28 克〔C53〕。"}
            ),
        )
    )
    c = asyncio.run(
        consult(SPECS[Role.NUTRITION], "我每天该吃多少蛋白质", [], (), tb, llm, solo=True)
    )
    composed = solo(c)
    assert [cid for cid, _ in composed.calcs] == ["C52", "C53"]
    assert "每天蛋白质" in sources_text(composed) and "K09" in sources_text(composed)


def _plan_json(minutes: int, moves: list[tuple[str, int]]) -> dict[str, Any]:
    return {
        "title": "三练",
        "days_per_week": 1,
        "sessions": [
            {
                "day": 1,
                "name": "全身",
                "minutes": minutes,
                "items": [{"exercise": e, "sets": n, "reps": "8–12"} for e, n in moves],
            }
        ],
    }


def test_plan_that_fails_check_is_sent_back_once() -> None:
    from types import SimpleNamespace

    from ironm_agent.constraints import Context
    from ironm_agent.experts import Opinion
    from ironm_agent.plugin import IronMAgent
    from ironm_agent.training import parse_plan

    too_long = _plan_json(
        45, [("高脚杯深蹲", 4), ("哑铃卧推", 4), ("单臂哑铃划船", 4), ("哑铃推举", 4)]
    )
    fits = _plan_json(45, [("高脚杯深蹲", 3), ("哑铃卧推", 3), ("单臂哑铃划船", 3)])
    plan = parse_plan(too_long)[0]
    assert plan is not None
    llm = FakeLLM(scripted(jsonr({"plan": fits})))
    lead = SimpleNamespace(opinion=Opinion(role=Role.TRAINER, speak=True, answer="三练全身"))
    case = SimpleNamespace(text=lambda **_: "档案")
    run: dict[str, Any] = {}
    new, _ = asyncio.run(
        IronMAgent._check_plan(
            IronMAgent(),
            plan,
            too_long,
            "帮我排计划",
            lead,
            None,
            ctx(),
            Context(),
            llm,
            case,
            run,  # type: ignore[arg-type]
        )
    )
    assert run["plan_check"] == "fixed" and len(new.sessions[0].items) == 3
    asked = str(llm.seen[0][1][-1]["content"])
    assert "没有通过检查" in asked and "超过了 45 分钟" in asked


def test_plan_that_passes_check_is_kept() -> None:
    from types import SimpleNamespace

    from ironm_agent.constraints import Context
    from ironm_agent.plugin import IronMAgent
    from ironm_agent.training import parse_plan

    fits = _plan_json(45, [("高脚杯深蹲", 3), ("哑铃卧推", 3)])
    plan = parse_plan(fits)[0]
    llm = FakeLLM(scripted())
    run: dict[str, Any] = {}
    new, _ = asyncio.run(
        IronMAgent._check_plan(
            IronMAgent(),
            plan,
            fits,
            "x",
            SimpleNamespace(),
            None,
            ctx(),
            Context(),
            llm,
            SimpleNamespace(),
            run,  # type: ignore[arg-type]
        )
    )
    assert run["plan_check"] == "pass" and new is plan and not llm.calls
