"""专业工具接进作答链路（spec [2026-10-23] §12）：只给对应角色、结果带编号、能通过核对、各角色有自己的思考框架。"""

import asyncio
from datetime import date
from typing import Any

from ironm_agent.kb import default_kb
from ironm_agent.llm import Reply, ToolCall
from ironm_agent.metrics import Readings
from ironm_agent.protools.registry import ToolContext
from ironm_agent.roles import EXPERTS, SPECS, Role
from ironm_agent.tools import Toolbox

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


def test_substitutes_adopt_library_entries_for_citation() -> None:
    tb = box(Role.RECOVERY, ctx(injured=["joint.knee"], equipment_said=["家里有哑铃"]))
    out = asyncio.run(tb.run(ToolCall("x", "find_substitutes", {"exercise": "杠铃深蹲"})))
    assert "箱式深蹲" in out
    assert any(e.title == "箱式深蹲" for e in tb.evidence.entries.values())


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


def new_plan_desk(
    current: Any = None, text: str = "帮我排计划", tools: Any = None
) -> tuple[Any, dict[str, Any]]:
    """交新计划的工具（§120），用内存里的训练存储。"""
    from ironm_agent.actions import Desk
    from ironm_agent.constraints import Context
    from ironm_agent.plugin import IronMAgent
    from ironm_agent.training import TrainingBook

    a = IronMAgent()
    a._training = TrainingBook()
    run: dict[str, Any] = {}
    handlers = a._action_handlers("42", text, current, Context(), TODAY, run, tools or ctx(),
                                  confirmed=True, merge=False, blocked=False)  # fmt: skip
    desk = Desk(handlers, has_plan=current is not None)
    desk.unlock(handlers)
    return desk, run


def test_plan_that_fails_check_is_sent_back_once() -> None:
    from ironm_agent.actions import NEW_PLAN

    too_long = _plan_json(
        45, [("高脚杯深蹲", 4), ("哑铃卧推", 4), ("单臂哑铃划船", 4), ("哑铃推举", 4)]
    )
    fits = _plan_json(45, [("高脚杯深蹲", 3), ("哑铃卧推", 3), ("单臂哑铃划船", 3)])
    desk, run = new_plan_desk()
    said = asyncio.run(desk.run(NEW_PLAN, {"plan": too_long, "changes": "", "kind": "new"}))
    assert "计划检查没过" in said and "超过了 45 分钟" in said and desk.plan is None  # 退回给它改
    said = asyncio.run(desk.run(NEW_PLAN, {"plan": fits, "changes": "", "kind": "new"}))
    assert said.startswith("已出") and run["plan_check"] == "fixed" and desk.plan is not None


def test_plan_that_passes_check_is_kept() -> None:
    from ironm_agent.actions import NEW_PLAN

    fits = _plan_json(45, [("高脚杯深蹲", 3), ("哑铃卧推", 3)])
    desk, run = new_plan_desk()
    said = asyncio.run(desk.run(NEW_PLAN, {"plan": fits, "changes": "", "kind": "new"}))
    assert said.startswith("已出") and run["plan_check"] == "pass" and run["preview"] == "plan"
