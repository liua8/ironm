"""动作工具第 2 批（spec [2026-10-23] §122）：今天的状态、身体数据、记一餐、只改今天、调热量。

用内存存储和假模型；不连数据库、不调用真实模型。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

import pytest

from ironm_agent.actions import (
    ADJUST_TODAY,
    ALWAYS,
    KCAL_CHANGE,
    LOG_BODY,
    LOG_MEAL,
    MAX_ACTIONS,
    NUDGE_CLAIM,
    RECORD_STATE,
    Desk,
)
from ironm_agent.constraints import Context
from ironm_agent.day_state import DayBook
from ironm_agent.diet_adjust import DietBook
from ironm_agent.meals import MealBook
from ironm_agent.plugin import IronMAgent
from ironm_agent.readings import ReadingBook
from ironm_agent.training import TrainingBook
from tests.fakes import acting, call, jsonr
from tests.test_plan_ops import plan as seeded_plan
from tests.test_plugin import text_of
from tests.test_protools_wiring import ctx

TODAY = date(2026, 10, 23)  # 周五：seeded_plan 周一、三、五练，今天是"上肢拉"那一次


def harness(
    monkeypatch: pytest.MonkeyPatch,
    text: str,
    *,
    current: Any = None,
    snapshot: Any = None,
    blocked: bool = False,
) -> tuple[IronMAgent, Desk, dict[str, Any], list[str]]:
    """直接拿处理函数和工具台：内存存储；管家重新评估只记下原因。"""
    from ironm_agent import plugin

    coached: list[str] = []

    async def coach(user_id: str, reason: str, force: bool) -> None:
        coached.append(reason)

    monkeypatch.setattr(plugin, "default_coach_eval", coach)
    a = IronMAgent()
    a._training, a._readings, a._meals, a._diet, a._day = (
        TrainingBook(), ReadingBook(), MealBook(), DietBook(), DayBook(),
    )  # fmt: skip
    run: dict[str, Any] = {}
    handlers = a._action_handlers("42", text, current, Context(), TODAY, run, ctx(), confirmed=True,
                                  merge=False, blocked=blocked, snapshot=snapshot)  # fmt: skip
    desk = Desk(handlers, has_plan=current is not None)
    desk.unlock(handlers)
    return a, desk, run, coached


def go(a: IronMAgent, desk: Desk, name: str, **args: Any) -> str:
    async def once() -> str:
        said = await desk.run(name, args)
        await a.settle()
        return said

    return asyncio.run(once())


def snapshot_with_target() -> Any:
    from tests.test_adjust import snap_with

    s = snap_with("fat_loss", -0.5)
    return s.__class__(s.profile, s.readings, s.metrics, TODAY)


# ---- 今天的状态 --------------------------------------------------------------------------------


def test_record_state_collects_what_he_said_and_is_not_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, desk, _, _ = harness(monkeypatch, "今天好累，只有半小时")
    for _ in range(MAX_ACTIONS + 2):
        assert go(a, desk, RECORD_STATE, tired=True, minutes=30, bogus=1).startswith("收到")
    assert desk.said == {"tired": True, "minutes": 30} and desk.calls == 0  # 不计次、多余字段不要
    assert "没写" in go(a, desk, RECORD_STATE)  # 空的退回


def test_said_is_gone_from_the_prompt_and_the_answer() -> None:
    from ironm_agent import agent, experts

    assert '"said"' not in agent._PROMPT and "record_state" in agent.RECORD_INLINE  # 切回当场记时才提（§166）
    assert "said" not in experts.Opinion.model_fields


# ---- 身体数据 ----------------------------------------------------------------------------------


def test_log_body_writes_only_numbers_he_said(monkeypatch: pytest.MonkeyPatch) -> None:
    a, desk, _, coached = harness(monkeypatch, "今天早上称了 72.5 公斤，腰围七十八")
    said = go(a, desk, LOG_BODY, kind="weight", value=72.5)
    assert said.startswith("已记下") and "72.5 公斤" in said and coached == ["记数据"]
    assert go(a, desk, LOG_BODY, kind="waist", value=78).startswith("已记下")  # 中文数字也认
    assert "不在他这句话里" in go(a, desk, LOG_BODY, kind="weight", value=71)  # 编的数
    assert "已经记过" in go(a, desk, LOG_BODY, kind="weight", value=72.5)  # 同一天同样的数
    assert [r["value"] for r in a._readings.rows["42"]] == [72.5, 78]


def test_log_body_refuses_out_of_range_and_bad_days(monkeypatch: pytest.MonkeyPatch) -> None:
    a, desk, _, _ = harness(monkeypatch, "体重 7 公斤，下周三再称")
    assert "没记" in go(a, desk, LOG_BODY, kind="weight", value=7)  # 范围不对
    a, desk, _, _ = harness(monkeypatch, "体重 70")
    future = (TODAY + timedelta(days=3)).isoformat()
    assert "日期只能是" in go(a, desk, LOG_BODY, kind="weight", value=70, day=future)
    assert "要写哪一项" in go(a, desk, LOG_BODY, kind="height", value=70)


# ---- 记一餐 ------------------------------------------------------------------------------------


def test_log_meal_is_counted_from_the_food_library(monkeypatch: pytest.MonkeyPatch) -> None:
    from ironm_agent.meals import food_line

    a, desk, _, coached = harness(monkeypatch, "中午吃了一碗米饭", snapshot=snapshot_with_target())
    said = go(a, desk, LOG_MEAL, kind="午餐", foods=[{"name": "米饭", "grams": 150}])
    want = round(food_line("米饭", 150).macros.kcal)
    assert said.startswith("已记下午餐") and f"约 {want} 千卡" in said and "还能吃约" in said
    meals = asyncio.run(a._meals.day("42", TODAY))
    assert len(meals) == 1 and round(meals[0].meal.macros.kcal) == want and coached == ["记饮食"]


def test_log_meal_uses_the_estimate_only_when_the_library_has_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, desk, _, _ = harness(monkeypatch, "吃了一份奇怪的东西")
    odd = {"name": "外星果冻", "grams": 100}
    assert "没记" in go(a, desk, LOG_MEAL, kind="加餐", foods=[odd])  # 库里没有又没估值
    per100 = {"kcal": 80, "protein_g": 1, "carbs_g": 18, "fat_g": 0}
    said = go(a, desk, LOG_MEAL, kind="加餐", foods=[{**odd, "per100": per100}])
    assert said.startswith("已记下") and "约 80 千卡" in said
    meal = asyncio.run(a._meals.day("42", TODAY))[0].meal
    assert "按估算" in meal.note and "对话里记的" in meal.note
    assert "要写哪一餐" in go(a, desk, LOG_MEAL, kind="下午茶", foods=[odd])


# ---- 只改今天 ----------------------------------------------------------------------------------


def test_adjust_today_scales_and_edits_only_today(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = seeded_plan()
    a, desk, run, coached = harness(monkeypatch, "今天只按七成练，引体向上去掉", current=plan)
    session = plan.session_on(TODAY)
    assert session is not None
    first = session.items[0].exercise
    said = go(a, desk, ADJUST_TODAY, ratio=0.7, changes=[{"kind": "remove", "exercise": first}])
    assert said.startswith("已改好今天这一次") and "计划页能恢复今天原样" in said
    state = asyncio.run(a._day.get("42", TODAY))
    assert state is not None and state.edits and state.edits[0].line  # 存进今天的状态
    assert run["today_edits"] >= 2 and coached == ["只改今天"]
    assert plan.session_on(TODAY) == session  # 原计划不变


def test_adjust_today_refuses_rest_days_no_plan_and_bad_ratios(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, desk, _, _ = harness(monkeypatch, "今天轻点", current=None)
    assert "还没有训练计划" in go(a, desk, ADJUST_TODAY, ratio=0.7)
    rest_plan = seeded_plan().model_copy(
        update={"sessions": seeded_plan().sessions[:1]}
    )  # 只有周一
    a, desk, _, _ = harness(monkeypatch, "今天轻点", current=rest_plan)
    assert "今天按计划不练" in go(a, desk, ADJUST_TODAY, ratio=0.7)
    a, desk, _, _ = harness(monkeypatch, "今天轻点", current=seeded_plan())
    assert "0.5–0.9" in go(a, desk, ADJUST_TODAY, ratio=0.2)
    assert "没写要怎么改" in go(a, desk, ADJUST_TODAY)


def test_adjust_today_is_not_given_on_a_data_risk_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    _, desk, _, _ = harness(monkeypatch, "今天轻点", current=seeded_plan(), blocked=True)
    assert ADJUST_TODAY not in desk.handlers and set(ALWAYS) - {"remember"} <= set(
        desk.handlers
    )  # 记忆另测（§145）


# ---- 调热量 ------------------------------------------------------------------------------------


def test_kcal_change_keeps_the_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    a, desk, _, coached = harness(monkeypatch, "热量往上调 200", snapshot=snapshot_with_target())
    said = go(a, desk, KCAL_CHANGE, delta=200, reason="他说饿")
    assert said.startswith("已调好") and coached == ["调热量"]
    got = asyncio.run(a._diet.current("42"))
    assert got is not None and got.kcal == 200
    said = go(a, desk, KCAL_CHANGE, delta=900, reason="还要多")  # 累计不超过 ±500
    assert asyncio.run(a._diet.current("42")).kcal == 500 and "按上下限" in said  # type: ignore[union-attr]
    assert "上限" in go(a, desk, KCAL_CHANGE, delta=100, reason="再加")
    a, desk, _, _ = harness(monkeypatch, "热量调一下")  # 算不出目标
    assert "算不出来" in go(a, desk, KCAL_CHANGE, delta=-100, reason="x")


def test_kcal_change_never_goes_below_the_safe_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    a, desk, _, _ = harness(monkeypatch, "少吃 2000", snapshot=snapshot_with_target())
    said = go(a, desk, KCAL_CHANGE, delta=-2000, reason="他要")
    if said.startswith("已调好"):  # 按下限调到能调的
        after = int(said.split("→ ")[1].split(" ")[0])
        from ironm_agent.metrics import safe_floor

        bmr = next(m for m in snapshot_with_target().metrics if m.key == "bmr").value
        assert after >= safe_floor(bmr, snapshot_with_target().profile)  # type: ignore[arg-type]
    else:
        assert "没调" in said


# ---- 说了做却没做、整轮 ------------------------------------------------------------------------


def test_saying_logged_needs_a_record_and_saying_adjusted_needs_a_change() -> None:
    """记录类（训练、一餐、读数、状态）任何一样做成，说"记下了"都算；修改类（计划、今天、热量）同理。"""
    from ironm_agent.actions import Outcome

    d = Desk({})
    assert d.unmet("记下了，这顿蛋白质够了。") == {"log"}
    assert d.unmet("热量已经调好了。") == {"change"}
    d.saved.append(Outcome(True, "", kind="saved", what="body"))
    assert d.unmet("记下了，这顿蛋白质够了。") == set()
    d.changed.append(Outcome(True, "", kind="changed", what="kcal"))
    assert d.unmet("热量已经调好了。") == set()
    # 复核 11-03：这几句曾被细分判错、整段删掉
    assert (
        Desk({}, said={"tired": True}).unmet("记下了，你昨晚睡得少，今天的训练减到七成。") == set()
    )
    assert Desk({}, said={"tired": True}).unmet("收到，你今天很累，记下了，今天训练减量。") == set()
    k = Desk({})
    k.changed.append(Outcome(True, "", kind="changed", what="kcal"))
    assert k.unmet("已经调好了，从今天开始每天多吃 200。") == set()


def test_a_meal_said_in_chat_is_recorded_in_the_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_single_agent import single

    a, _ = single(acting(LOG_MEAL, {"kind": "午餐", "foods": [{"name": "米饭", "grams": 150}]},
                         {"answer": "记下了，这顿碳水够了，晚上多吃点蛋白质〔经验〕。"}, tries=1),
                  monkeypatch, old=True)  # fmt: skip
    a._meals = MealBook()
    from tests.test_turn_flow import run

    blocks, seen = run(a, "中午吃了一碗米饭")
    assert seen["actions"] == [{"tool": LOG_MEAL, "result": "ok"}] and not seen.get("unacted")
    assert "记下了" in text_of(blocks) and len(asyncio.run(a._meals.day("42", TODAY))) == 1


def test_claiming_a_meal_was_logged_without_the_tool_is_nudged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.test_single_agent import single
    from tests.test_turn_flow import run

    lasts: list[str] = []

    def answer(system: str, user: str, results: list[str]) -> Any:
        lasts.append(s.last)
        return jsonr({"answer": "记下了，这顿碳水够了。"})

    a, s = single(answer, monkeypatch, old=True)
    blocks, seen = run(a, "中午吃了一碗米饭")
    assert NUDGE_CLAIM in lasts and seen["unacted"] and "记下了" not in text_of(blocks)


def test_state_said_in_chat_goes_through_the_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_single_agent import single
    from tests.test_turn_flow import run

    def answer(system: str, user: str, results: list[str]) -> Any:
        if not results:
            return call(RECORD_STATE, tired=True, sleep=5)
        return jsonr({"answer": "今天按七成练〔经验〕。"})

    a, _ = single(answer, monkeypatch, old=True)
    a._day = DayBook()
    _, seen = run(a, "昨晚只睡了 5 个小时，好累")
    asyncio.run(a.settle())
    state = asyncio.run(a._day.get("42", date.today()))
    assert seen["state_by"] == "model" and state is not None
    assert {e.kind for e in state.entries} == {"tired", "sleep"}


def test_logs_have_tool_names_and_results_only(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="ironm_agent.actions")
    a, desk, _, _ = harness(
        monkeypatch, "中午吃了一碗米饭，体重 72", snapshot=snapshot_with_target()
    )
    go(a, desk, LOG_MEAL, kind="午餐", foods=[{"name": "米饭", "grams": 150}])
    go(a, desk, LOG_BODY, kind="weight", value=72)
    lines = [r.getMessage() for r in caplog.records if r.name == "ironm_agent.actions"]
    assert lines == [f"action: tool={LOG_MEAL} result=ok", f"action: tool={LOG_BODY} result=ok"]
    assert all("米饭" not in x and "72" not in x for x in lines)


def test_what_the_coach_hands_in_is_kept_as_is(monkeypatch: pytest.MonkeyPatch) -> None:
    """§163 规则不要：代码不再把"哪里疼"里的肚子疼改判成生病，管家交什么就是什么（肚子疼由它写进 sick）。"""
    a, desk, _, _ = harness(monkeypatch, "肚子疼，今天能练吗")
    go(a, desk, RECORD_STATE, sick="肚子疼", sick_level="颈部以下")
    assert desk.said == {"sick": "肚子疼", "sick_level": "颈部以下"}
    go(a, desk, RECORD_STATE, pain=[{"part": "膝", "side": "左", "exercise": "深蹲"}])
    assert desk.said["pain"] == [{"part": "膝", "side": "左", "exercise": "深蹲"}]


# ---- 独立审查（11-03）提的问题 ----------------------------------------------------------------


def test_adjust_today_stores_only_what_was_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    """第 1 条：被挡下的换动作不存；被换成替代动作的按实际换上的存，今天的版本里不出现压伤处的动作。"""
    from ironm_agent.plan_edit import today_session

    plan = seeded_plan()
    session = plan.session_on(TODAY)
    assert session is not None
    first, second = session.items[0].exercise, session.items[1].exercise
    a, desk, _, _ = harness(monkeypatch, "今天换一下", current=plan)
    desk.handlers  # noqa: B018
    from tests.test_protools_wiring import ctx as tool_ctx

    hurt = tool_ctx(injured=["joint.lumbar"])
    handlers = a._action_handlers("42", "今天换一下", plan, Context(), TODAY, {}, hurt, confirmed=True,
                                  merge=False, blocked=False)  # fmt: skip
    d = Desk(handlers, has_plan=True)
    d.unlock(handlers)
    said = go(a, d, ADJUST_TODAY, changes=[{"kind": "edit", "exercise": first, "sets": 2},
                                           {"kind": "swap", "exercise": second, "to": "杠铃硬拉"}])  # fmt: skip
    state = asyncio.run(a._day.get("42", TODAY))
    assert state is not None
    names = [x.exercise for x in today_session(session, state.edits).items]
    assert "杠铃硬拉" not in names  # 腰伤：硬拉要么没换上、要么换成了替代动作，存下的和说的一致
    stored = [e for e in state.edits if e.kind == "swap"]
    assert all(e.to in names for e in stored)
    assert said.startswith("已改好")


def test_weight_said_in_jin_is_converted(monkeypatch: pytest.MonkeyPatch) -> None:
    """第 2 条：说"斤"按斤换算成公斤，不把 140 斤记成 140 公斤。"""
    a, desk, _, _ = harness(monkeypatch, "今天早上称了 140 斤")
    said = go(a, desk, LOG_BODY, kind="weight", value=140)
    assert "70 公斤" in said and "140 斤" in said
    assert [r["value"] for r in a._readings.rows["42"]] == [70]
    assert "不在他这句话里" in go(
        a, desk, LOG_BODY, kind="weight", value=70
    )  # 自己换算了：写原话的数


def test_bad_day_is_refused_not_silently_today(monkeypatch: pytest.MonkeyPatch) -> None:
    a, desk, _, _ = harness(monkeypatch, "昨天体重 70")
    assert "YYYY-MM-DD" in go(a, desk, LOG_BODY, kind="weight", value=70, day="昨天")


def test_meal_keeps_one_per_kind_a_day(monkeypatch: pytest.MonkeyPatch) -> None:
    """第 4 条：同一种餐今天只留一份（§43，同饮食页），重复调不会叠加。"""
    a, desk, _, _ = harness(monkeypatch, "中午吃了一碗米饭", snapshot=snapshot_with_target())
    go(a, desk, LOG_MEAL, kind="午餐", foods=[{"name": "米饭", "grams": 150}])
    go(a, desk, LOG_MEAL, kind="午餐", foods=[{"name": "米饭", "grams": 150}])
    go(a, desk, LOG_MEAL, kind="晚餐", foods=[{"name": "米饭", "grams": 100}])
    kinds = [m.meal.kind for m in asyncio.run(a._meals.day("42", TODAY))]
    assert sorted(kinds) == ["午餐", "晚餐"]
    assert "最多记" in go(
        a, desk, LOG_MEAL, kind="加餐", foods=[{"name": "米饭", "grams": 10}] * 13
    )


def test_turn_that_fails_still_says_what_was_done(monkeypatch: pytest.MonkeyPatch) -> None:
    """第 5 条：直接写入的不回退；这一轮没答出来时如实告诉他已经做了什么，免得他再说一遍又记一次。"""
    from ironm_agent.llm import Reply
    from tests.test_single_agent import cards, single
    from tests.test_turn_flow import run

    def answer(system: str, user: str, results: list[str]) -> Any:
        if not results:
            return call(LOG_BODY, kind="weight", value=72)
        return Reply('{"answer": "断了')  # 断掉的 JSON（正常的一段话会照正文用，§165）

    a, _ = single(answer, monkeypatch, old=True)
    a._readings = ReadingBook()
    blocks, seen = run(a, "体重 72")
    assert seen["path"] == "no_answer" and not cards(blocks)
    assert "这一轮已经做了：记下了体重 72 公斤" in text_of(blocks)


def test_second_kcal_change_in_a_turn_starts_from_the_new_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """第 6 条：同一轮第二次调热量从新的目标算，报的数和存下的一致；记一餐的"还能吃"也按新目标。"""
    snap = snapshot_with_target()
    start = next(m for m in snap.metrics if m.key == "kcal_target").value
    a, desk, _, _ = harness(monkeypatch, "加 200，再加 100，中午吃了一碗米饭", snapshot=snap)
    go(a, desk, KCAL_CHANGE, delta=200, reason="饿")
    said = go(a, desk, KCAL_CHANGE, delta=100, reason="还饿")
    assert f"{round(start + 200)} → {round(start + 300)}" in said
    meal = go(a, desk, LOG_MEAL, kind="午餐", foods=[{"name": "米饭", "grams": 150}])
    assert f"目标约 {round(start + 300)}" in meal


def test_minors_and_pregnancy_cannot_cut_calories_in_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    """第 7 条：18 岁以下、孕期在对话里减热量由代码挡下（加照常）。"""
    from ironm_agent.special import MINOR
    from tests.test_protools_wiring import ctx as tool_ctx

    a, _, _, _ = harness(monkeypatch, "再少吃 300", snapshot=snapshot_with_target())
    young = tool_ctx()
    young = young.__class__(**{**young.__dict__, "special": frozenset({MINOR})})
    handlers = a._action_handlers("42", "再少吃 300", None, Context(), TODAY, {}, young, confirmed=True,
                                  merge=False, blocked=False, snapshot=snapshot_with_target())  # fmt: skip
    d = Desk(handlers)
    d.unlock(handlers)
    assert "18 岁以下" in go(a, d, KCAL_CHANGE, delta=-300, reason="他要")
    assert go(a, d, KCAL_CHANGE, delta=150, reason="饿").startswith("已调好")


def test_ratio_rounds_like_the_plan_reduce_and_says_when_nothing_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """第 9 条：按几成练的取整和计划减量一样（四舍五入）；比例小到组数不变时说清楚。"""
    from ironm_agent.plan_edit import today_session

    base = seeded_plan()
    friday = base.session_on(TODAY)
    assert friday is not None
    five = friday.model_copy(
        update={"items": [friday.items[0].model_copy(update={"sets": 5}), *friday.items[1:]]}
    )
    plan = base.model_copy(
        update={"sessions": [five if x.day == friday.day else x for x in base.sessions]}
    )
    a, desk, _, _ = harness(monkeypatch, "今天按九成", current=plan)
    assert "组数没有变化" in go(a, desk, ADJUST_TODAY, ratio=0.9)
    go(a, desk, ADJUST_TODAY, ratio=0.5)
    session = plan.session_on(TODAY)
    assert session is not None
    state = asyncio.run(a._day.get("42", TODAY))
    got = {x.exercise: x.sets for x in today_session(session, state.edits).items}  # type: ignore[union-attr]
    assert got == {x.exercise: max(1, int(x.sets * 0.5 + 0.5)) for x in session.items}
    assert got[session.items[0].exercise] == 3  # 5 组按五成：四舍五入是 3（不是银行家取整的 2）


# ---- 复核（11-03）提的问题 ---------------------------------------------------------------------


def _today_sets(a: IronMAgent, session: Any) -> dict[str, int]:
    from ironm_agent.plan_edit import today_session

    state = asyncio.run(a._day.get("42", TODAY))
    assert state is not None
    return {x.exercise: x.sets for x in today_session(session, state.edits).items}


def test_ratio_is_applied_after_named_edits(monkeypatch: pytest.MonkeyPatch) -> None:
    """按几成练和具体改法一起给：按改完的算；他明说了组数的动作不再按比例减；不多出"没有某某"。"""
    plan = seeded_plan()
    session = plan.session_on(TODAY)
    assert session is not None
    first, second = session.items[0], session.items[1]
    a, desk, _, _ = harness(monkeypatch, "今天五成，第二个改 5 组", current=plan)
    said = go(a, desk, ADJUST_TODAY, ratio=0.5,
              changes=[{"kind": "edit", "exercise": second.exercise, "sets": 5}])  # fmt: skip
    got = _today_sets(a, session)
    assert got[second.exercise] == 5  # 他明说的不被比例盖掉
    assert got[first.exercise] == max(1, int(first.sets * 0.5 + 0.5))
    assert "没有" not in said


def test_ratio_also_scales_a_swapped_in_exercise(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = seeded_plan()
    session = plan.session_on(TODAY)
    assert session is not None
    first = session.items[0]
    a, desk, _, _ = harness(monkeypatch, "今天五成，第一个换成俯卧撑", current=plan)
    said = go(
        a,
        desk,
        ADJUST_TODAY,
        ratio=0.5,
        changes=[{"kind": "swap", "exercise": first.exercise, "to": "俯卧撑"}],
    )
    got = _today_sets(a, session)
    swapped = next(n for n in got if n not in {x.exercise for x in session.items})
    assert got[swapped] == max(1, int(first.sets * 0.5 + 0.5)) and "没有" not in said


def test_jin_in_chinese_numerals_and_mixed_units(monkeypatch: pytest.MonkeyPatch) -> None:
    """ "一百四十斤"不写单位也按斤；同一句里斤和公斤都有、又对不上数时问清楚。"""
    a, desk, _, _ = harness(monkeypatch, "今天称了一百四十斤")
    assert "70 公斤" in go(a, desk, LOG_BODY, kind="weight", value=140)
    a, desk, _, _ = harness(monkeypatch, "体重 72 公斤，上周 140 斤")
    assert "72 公斤" in go(a, desk, LOG_BODY, kind="weight", value=72)  # 数后面跟着公斤：按公斤
    a, desk, _, _ = harness(monkeypatch, "今天七十二公斤，上周一百四十斤")
    assert "看不出这个数是哪个单位" in go(a, desk, LOG_BODY, kind="weight", value=72)


def test_already_done_note_keeps_the_date(monkeypatch: pytest.MonkeyPatch) -> None:
    a, desk, _, _ = harness(monkeypatch, "昨天体重 72")
    go(a, desk, LOG_BODY, kind="weight", value=72, day=(TODAY - timedelta(days=1)).isoformat())
    assert desk.done_note() == "这一轮已经做了：记下了（10月22日）体重 72 公斤。"


def test_kcal_cut_stops_at_the_safe_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    """复核：原来这条测试 if/else 两边都能过。下调碰到下限时按下限调；已经在下限时退回。"""
    from ironm_agent.metrics import safe_floor

    snap = snapshot_with_target()
    by = {m.key: m.value for m in snap.metrics}
    floor = safe_floor(by["bmr"], snap.profile)  # type: ignore[arg-type]
    room = by["kcal_target"] - floor  # type: ignore[operator]
    assert 300 < room < 450  # 前提：一次调不到下限、碰到下限比碰到 ±500 先（档案变了这里会先报出来）
    a, desk, _, _ = harness(monkeypatch, "少吃一点", snapshot=snap)
    said = go(a, desk, KCAL_CHANGE, delta=-round(room) - 50, reason="他要")
    before = round(by["kcal_target"])  # type: ignore[arg-type]
    assert said.startswith("已调好") and f"→ {before - 300} 千卡" in said and "按上下限" in said  # 一次最多 300（§182）
    said = go(a, desk, KCAL_CHANGE, delta=-300, reason="他要")
    assert said.startswith("已调好") and f"→ {round(floor)} 千卡" in said and "按上下限" in said
    assert "不能再减" in go(a, desk, KCAL_CHANGE, delta=-50, reason="再少点")


def test_second_different_reading_on_a_day_says_one_per_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实回放（11-03）：线上一天一项只留一个，第二个不同的数没写进去，却说成"记过同样的数"。"""
    a, desk, _, _ = harness(monkeypatch, "早上 72.5，晚上 73")
    go(a, desk, LOG_BODY, kind="weight", value=72.5)

    async def one_per_day(user_id: str, kind: str, value: float, day: date) -> int:
        return 0

    a._readings.add = one_per_day  # type: ignore[method-assign]
    said = go(a, desk, LOG_BODY, kind="weight", value=73)
    assert "一天只记一个" in said and "72.5 公斤" in said


def test_a_meal_can_be_said_in_portions_and_its_numbers_can_be_cited(monkeypatch: pytest.MonkeyPatch) -> None:
    """复核 11-05：说"一碗""两个"的按食物库一份算；算出来的数登记成计算结果，回答里能引〔C…〕。"""
    from ironm_agent.checks import check_text
    from ironm_agent.foods import find
    from ironm_agent.meals import food_line

    a, desk, _, _ = harness(monkeypatch, "中午吃了一碗米饭两个包子", snapshot=snapshot_with_target())
    calcs: dict[str, str] = {}

    def add(detail: str) -> str:
        calcs[f"C{len(calcs) + 1}"] = detail
        return f"C{len(calcs)}"

    desk.on_calc = add
    said = go(a, desk, LOG_MEAL, kind="午餐", foods=[{"name": "米饭", "portions": 1}, {"name": "肉包", "portions": 2}])
    rice, bun = find("米饭"), find("肉包")
    assert rice is not None and bun is not None
    want = round(food_line("米饭", rice.unit_g).macros.kcal + food_line("肉包", 2 * bun.unit_g).macros.kcal)
    assert f"约 {want} 千卡" in said and f"米饭 1 {rice.unit}按 {round(rice.unit_g)} 克" in said
    assert "〔C1〕" in said and str(want) in calcs["C1"]
    answer = f"这一餐约 {want} 千卡〔C1〕。"
    assert check_text(answer, support={}, entries={}, question="", calcs=calcs) == []  # 能引、核对过得了
    assert "库里没有" in go(a, desk, LOG_MEAL, kind="晚餐", foods=[{"name": "外星菜", "portions": 1}])


def test_new_calc_numbers_do_not_collide_with_the_case_file() -> None:
    from types import SimpleNamespace

    from ironm_agent.tools import Evidence, Toolbox

    box = SimpleNamespace(evidence=Evidence())
    box.evidence.calcs.update({"C1": "基础代谢", "C7": "热量目标"})
    assert Toolbox.add_calc(box, "一餐 500 千卡") == "C8"  # type: ignore[arg-type]
    assert box.evidence.calcs["C8"] == "一餐 500 千卡"
