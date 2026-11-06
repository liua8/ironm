"""mirobody 与 iron-m 整合一期（spec [2026-10-23] §25）：iron-m 的工具登记到 mirobody、专业 Agent 用上
mirobody 的用药和医学知识、工具清单和实际登记一致。不连数据库、不调用真实模型。"""

import asyncio
from datetime import date, timedelta
from typing import Any

import pytest

from ironm_agent import mcp_tools
from ironm_agent.casefile import Snapshot
from ironm_agent.coach_state import CoachBook, Deps, evaluate
from ironm_agent.goal import Goal, GoalBook
from ironm_agent.meals import Macros, Meal, MealBook
from ironm_agent.memory_store import MemoryBook
from ironm_agent.metrics import Profile, Readings, compute_all
from ironm_agent.training import LogItem, Plan, SetDone, TrainingBook, WorkoutLog, plan_content

TODAY = date.today()


def tools() -> dict[str, Any]:
    """和 mirobody 服务端一样：按模块载入，再摊平成"工具名 → 工具"。"""
    from mirobody.mcp.tool import load_tools_from_module

    out: dict[str, Any] = {}
    for group in load_tools_from_module(mcp_tools, "ironm_agent.mcp_tools").values():
        out.update(group)
    return out


def snap() -> Snapshot:
    p = Profile(
        height_cm=178, birth=date(1994, 5, 1), sex="male", goal="muscle", activity="moderate"
    )
    r = Readings(
        weight=tuple((TODAY - timedelta(days=i), 75.0 + 0.02 * (27 - i)) for i in range(28))
    )
    return Snapshot(p, r, tuple(compute_all(r, p, TODAY)), TODAY)


@pytest.fixture
def data(monkeypatch: pytest.MonkeyPatch) -> mcp_tools.Sources:
    book = TrainingBook()
    plan = Plan.model_validate({"title": "增肌三练", "days_per_week": 3, "sessions": [
        {"day": TODAY.isoweekday(), "name": "下肢", "items": [{"exercise": "杠铃深蹲", "sets": 3, "reps": "6–8"}]}]})  # fmt: skip
    d = asyncio.run(book.add_draft("42", "plan", plan_content(plan)))
    asyncio.run(book.confirm("42", d.id))
    for back in (6, 2):
        asyncio.run(book.log("42", WorkoutLog(day=TODAY - timedelta(days=back), session="下肢", items=[
            LogItem(exercise="杠铃深蹲", done_sets=[SetDone(reps=9, weight_kg=80)] * 3)])))  # fmt: skip
    meals = MealBook()
    asyncio.run(meals.add("42", TODAY, Meal(kind="午餐", name="牛肉面",
                                            macros=Macros(kcal=650, protein_g=30, carbs_g=90, fat_g=18))))  # fmt: skip
    goals = GoalBook()
    goals.rows["42"] = Goal(80, TODAY + timedelta(days=120), TODAY - timedelta(days=10), start=75)
    s = snap()

    async def snapshot(_: str) -> Snapshot:
        return s

    src = mcp_tools.Sources(snapshot=snapshot, training=book, memory=MemoryBook(), meals=meals,
                            goals=goals, coach=CoachBook())  # fmt: skip
    monkeypatch.setattr(mcp_tools, "sources", lambda: src)
    return src


def call(name: str, arguments: dict[str, Any] | None = None, user_id: str = "42") -> Any:
    from mirobody.mcp.tool import call_tool

    return asyncio.run(call_tool(tools(), name, arguments or {}, user_id))


def text(out: Any) -> str:
    return str(out.get("result", out)) if isinstance(out, dict) else str(out)


def test_tools_load_with_hidden_identity() -> None:
    t = tools()
    assert set(t) == {"search_fitness_knowledge", "search_exercises", "estimate_strength",
                      "check_training_plan", "plan_templates", "training_patterns", "find_substitutes", "nutrition_calc",
                      "diet_templates",
                      "pain_check", "trend_analysis", "explain_trends", "query_my_training", "query_my_meals",
                      "query_my_goal", "query_coach_plan"}  # fmt: skip
    for name, tool in t.items():
        schema = tool["description"]["inputSchema"]
        assert "user_info" not in schema.get("properties", {}), name  # 身份由服务端注入，不给模型填
        assert tool["description"]["annotations"]["readOnlyHint"] is True, name
    assert not t["search_fitness_knowledge"]["auth"] and t["query_my_training"]["auth"]


def test_personal_tools_read_only_the_signed_in_person(data: mcp_tools.Sources) -> None:
    mine = text(call("query_my_training"))
    assert (
        "增肌三练" in mine
        and "杠铃深蹲 80×9" in mine
        and "下次 80 公斤 × 9 次 × 3 组（照上次" in mine
    )
    other = text(call("query_my_training", {"user_info": {"user_id": "42"}}, user_id="7"))
    assert "还没有" in other and "杠铃深蹲" not in other  # 模型传别人的编号也没用：只认登录身份
    assert asyncio.run(mcp_tools.MyFitnessService().query_my_training({})) == mcp_tools.NEED_LOGIN


def test_meals_goal_and_compute_tools(data: mcp_tools.Sources) -> None:
    meals = text(call("query_my_meals"))
    assert "牛肉面" in meals and "650 千卡" in meals and "热量" in meals
    assert "格式" in str(call("query_my_meals", {"day": "昨天"}))
    goal = text(call("query_my_goal"))
    assert "目标体重 80 公斤" in goal and "起点 75" in goal
    assert "由你决定" not in goal and "晚约" not in goal  # 只给事实（§182）
    assert "1RM" in text(
        call("estimate_strength", {"weight_kg": 80, "reps": 8})
    ) or "最大重量" in text(call("estimate_strength", {"weight_kg": 80, "reps": 8}))
    assert "蛋白质" in text(call("nutrition_calc", {"items": ["protein"]}))  # 按记录里的体重算
    assert "可以换成" in text(call("find_substitutes", {"exercise": "杠铃深蹲"}))
    assert "训练" in text(call("training_patterns", {"days": 14}))


def test_knowledge_tools_need_no_login() -> None:
    assert "K" in text(call("search_fitness_knowledge", {"query": "肌酸 剂量"}, user_id=""))
    assert "深蹲" in text(call("search_exercises", {"query": "深蹲"}, user_id=""))


def test_coach_plan_tool(data: mcp_tools.Sources) -> None:
    assert "还没有" in text(call("query_coach_plan"))
    deps = Deps(snapshot=data.snapshot, training=data.training, pain=__import__("ironm_agent.triggers",
                fromlist=["PainBook"]).PainBook(), goals=data.goals,
                diet=__import__("ironm_agent.diet_adjust", fromlist=["DietBook"]).DietBook(), store=data.coach)  # fmt: skip
    asyncio.run(evaluate("42", deps, reason="打卡"))
    out = text(call("query_coach_plan"))
    assert "当前方案第 1 版" in out and "管家正在看今天的情况" in out and "最近的调整经历" in out


def test_catalog_matches_what_is_registered() -> None:
    from ironm_agent import tools as agent_tools
    from ironm_agent.protools.registry import TOOLS
    from ironm_agent.roles import EXPERTS, SPECS
    from ironm_agent.tool_catalog import CATALOG

    ours = {t.mcp for t in CATALOG if t.source == "iron-m" and t.mcp}
    assert ours == set(tools())  # 清单里 iron-m 在 MCP 上的，就是实际登记的
    by_agent = {t.agent: t for t in CATALOG if t.agent}
    for name, tool in TOOLS.items():
        assert by_agent[name].roles == tool.roles, name
    assert by_agent["search_exercises"].roles == agent_tools.LIBRARY_ROLES
    assert by_agent["compute_metrics"].roles == agent_tools.METRIC_ROLES
    assert by_agent["query_medications"].roles == agent_tools.MEDS_ROLES
    assert by_agent["search_medical_knowledge"].roles == agent_tools.MEDICAL_ROLES
    health = {r.value for r in EXPERTS if SPECS[r].health_data} | {"general"}
    assert by_agent["query_health_indicators"].roles == health
    from mirobody.agent.tools import medications_service

    assert medications_service.MedicationsService.TOOL_NAME == "query_medications"


def test_agents_get_medications_and_medical_knowledge() -> None:
    from ironm_agent.kb import default_kb
    from ironm_agent.llm import ToolCall
    from ironm_agent.roles import SPECS, Role
    from ironm_agent.tools import MEDICAL, MEDS, Toolbox

    asked: list[Any] = []

    class FakeMeds:
        async def query_medications(self, user_info: dict[str, Any], **args: Any) -> dict[str, Any]:
            asked.append(user_info)
            return {"result": "美托洛尔 25 mg，每天一次"}

    async def medical(query: str, scope: str) -> str:
        return f"MedlinePlus：{query}"

    def box(role: Role) -> Toolbox:
        return Toolbox(SPECS[role], kb=default_kb(), health=None, user_id="42", session_id="s",
                       meds=FakeMeds(), medical=medical)  # fmt: skip

    def names(tb: Toolbox) -> set[str]:
        return {s["function"]["name"] for s in tb.schemas()}

    assert {MEDS, MEDICAL} <= names(box(Role.RECOVERY))
    assert MEDICAL in names(box(Role.NUTRITION)) and MEDS not in names(box(Role.NUTRITION))
    assert not {MEDS, MEDICAL} & names(box(Role.TRAINER))
    rec = box(Role.RECOVERY)
    assert "美托洛尔" in asyncio.run(rec.run(ToolCall("x", MEDS, {})))
    assert asked == [{"user_id": "42", "session_id": "s"}]
    assert "MedlinePlus" in asyncio.run(rec.run(ToolCall("y", MEDICAL, {"query": "metoprolol"})))
    refused = asyncio.run(box(Role.TRAINER).run(ToolCall("z", MEDS, {})))
    assert "不能使用" in refused
