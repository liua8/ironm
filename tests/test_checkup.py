"""每日复盘叫醒管家做到期复查（spec [2026-10-23] §129）：同一份规程、同一套工具；改计划出预览、他同意才保存。

不连数据库、不调用真实模型。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

import pytest

from ironm_agent import review
from ironm_agent.metrics import KcalAdjust
from tests.fakes import FakeLLM, call, jsonr
from tests.test_coach import TODAY
from tests.test_review import facts_id, model, setup


def systems(llm: FakeLLM) -> str:
    return "\n".join(str(m[1][0]["content"]) for m in llm.seen)


def test_which_skills_are_checked_when() -> None:
    """今天练不练每次都查；满 14 天没调热量才查饮食；满 4 周才查计划；规程的"到期复查"一节交给管家。"""
    dp = setup()
    llm, _ = model()
    asyncio.run(review.run("42", dp, llm))
    first = systems(llm)
    assert (
        "【今天练不练 · 到期复查】" in first and "【饮食方案 · 到期复查】" in first
    )  # 从没调过热量
    assert "【排训练计划 · 到期复查】" in first  # 这周第一次复查：看一眼这周（§163）
    asyncio.run(dp.diet.apply("42", KcalAdjust(-200, TODAY, "x")))
    llm, _ = model()
    asyncio.run(review.run("42", dp, llm, force=True))
    again = systems(llm)
    assert "饮食方案" not in again  # 刚调过：不到 14 天不查
    assert "排训练计划" not in again and "propose_plan_edit" not in again.split("装上的规程")[0]  # 同一周再查：不再看计划
    llm, _ = model()
    asyncio.run(review.run("42", dp, llm, force=True, today=TODAY + timedelta(days=28)))
    staged = systems(llm)
    assert "【排训练计划 · 到期复查】" in staged and "阶段小结" in staged  # 满 4 周：查计划、写小结


def test_old_review_prompt_is_gone_and_the_skills_share_the_section() -> None:
    from ironm_agent.skills import by_id

    assert '"adjust"' not in review._PROMPT and "到期复查" in review._PROMPT
    for i in ("readiness-adjust", "diet-plan", "plan-build"):
        x = by_id(i)
        assert x is not None and x.section("到期复查")  # 对话里也能取这一节（同一份规程）


def test_the_same_item_twice_keeps_the_last_and_retires_the_earlier_proposal() -> None:
    dp = setup()
    stage = TODAY + timedelta(days=28)
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe, today=stage))
    f = facts_id(seen, "当前计划")
    day = TODAY.isoweekday()
    llm, _ = model(
        {"type": "today", "ratio": 0.6, "why": "先轻点", "basis": [f]},
        {"type": "today", "ratio": 0.8, "why": "八成就够", "basis": [f]},
        {"type": "plan", "why": "a", "basis": [f], "ops": [{"kind": "swap", "day": day, "exercise": "杠铃深蹲", "to": "高脚杯深蹲"}]},
        {"type": "plan", "why": "b", "basis": [f], "ops": [{"kind": "reduce", "day": day, "ratio": 0.7}]},
    )  # fmt: skip
    got = asyncio.run(review.run("42", dp, llm, force=True, today=stage))
    assert [(d.type, d.why) for d in got.done] == [("today", "八成就够"), ("propose", "b")]
    pending = [d for d in dp.training._drafts["42"].values() if d.state == "pending"]
    assert len(pending) == 1  # 前一份预览作废


def test_partial_results_are_kept_when_the_model_breaks_midway() -> None:
    """调完一项后模型挂了：已经生效的照记（能撤销），不当成没复盘。"""
    dp = setup()
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe))
    f = facts_id(seen, "每日热量目标")
    turns = iter([call("propose_kcal_change", delta=150, why="饿", basis=[f])])

    def answer(*_: Any) -> Any:
        try:
            return next(turns)
        except StopIteration:
            raise RuntimeError("模型挂了") from None

    got = asyncio.run(review.run("42", dp, FakeLLM(answer), force=True))
    assert [d.type for d in got.done] == ["kcal"]  # 已经生效的照记
    assert got.failed  # 没就今天做出决定：今天照规则兜底（审查 11-03 第 10 条）
    assert asyncio.run(review.undo("42", dp, "review:kcal")) is not None


def test_the_pending_proposal_is_what_the_page_gets(monkeypatch: pytest.MonkeyPatch) -> None:
    """他点"确认，出方案"：页面拿到的就是复查存好的那份预览，不再重新生成。"""
    from ironm_agent import web_more

    dp = setup()
    stage = TODAY + timedelta(days=28)
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe, today=stage))
    f = facts_id(seen, "当前计划")
    op = {"kind": "swap", "day": TODAY.isoweekday(), "exercise": "杠铃深蹲", "to": "高脚杯深蹲"}
    llm, _ = model({"type": "plan", "why": "膝盖不舒服先换", "basis": [f], "ops": [op]})
    got = asyncio.run(review.run("42", dp, llm, force=True, today=stage))
    monkeypatch.setattr(web_more, "coach_deps", lambda: dp)
    monkeypatch.setattr(web_more, "date", type("D", (), {"today": staticmethod(lambda: stage)}))
    out = asyncio.run(web_more._checkup_proposal("42", dp.training))
    assert (
        out is not None
        and out["status"] == "ok"
        and out["draft"]["id"] == got.done[0].value["draft"]
    )
    asyncio.run(dp.training.cancel("42", str(got.done[0].value["draft"])))
    gone = asyncio.run(web_more._checkup_proposal("42", dp.training))
    assert gone is not None and gone["status"] == "no_change"  # 作废了就不再给，也不重新生成另一份


def test_logs_have_tool_names_and_results_only(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="ironm_agent.review")
    dp = setup()
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe))
    f = facts_id(seen, "当前计划")
    llm, _ = model({"type": "today", "ratio": 0.7, "why": "这周练多了", "basis": [f]},
                   {"type": "note", "text": "早点睡", "why": "睡少了", "basis": ["F999"]})  # fmt: skip
    asyncio.run(review.run("42", dp, llm, force=True))
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("review tool")]
    assert lines == [
        "review tool: tool=adjust_today result=ok",
        "review tool: tool=coach_note result=rejected",
    ]
    assert not any(
        "早点睡" in r.getMessage() or "这周练多了" in r.getMessage() for r in caplog.records
    )


def test_confirm_button_returns_the_stored_preview_from_the_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """接口层：/review/proposal 先给复查存好的预览，不走规则或再请管家生成。"""
    from ironm_agent import web_more

    dp = setup()
    stage = TODAY + timedelta(days=28)
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe, today=stage))
    f = facts_id(seen, "当前计划")
    op = {"kind": "swap", "day": TODAY.isoweekday(), "exercise": "杠铃深蹲", "to": "高脚杯深蹲"}
    llm, _ = model({"type": "plan", "why": "膝盖不舒服先换", "basis": [f], "ops": [op]})
    got = asyncio.run(review.run("42", dp, llm, force=True, today=stage))
    monkeypatch.setattr(web_more, "coach_deps", lambda: dp)
    monkeypatch.setattr(web_more, "date", type("D", (), {"today": staticmethod(lambda: stage)}))

    def no_regenerate(*_: Any, **__: Any) -> Any:
        raise AssertionError("不该重新生成")

    monkeypatch.setattr(web_more, "_web", no_regenerate)
    out = asyncio.run(web_more.review_proposal(trigger="", user_id="42", training=dp.training))
    assert out["status"] == "ok" and out["draft"]["id"] == got.done[0].value["draft"]


def test_saying_an_adjustment_without_calling_the_tool_is_nudged_once() -> None:
    """真实模型（11-03）：总结里写"今天按六到八成练"却没调用工具，什么都没生效；提醒一次。"""
    dp = setup()
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe))
    f = facts_id(seen, "当前计划")
    asked: list[str] = []

    def answer(stage: Any, messages: Any, tools: Any) -> Any:
        last = str(messages[-1]["content"])
        asked.append(last)
        if last == review.NUDGE:
            return call("adjust_today", ratio=0.7, why="恢复不够", basis=[f])
        if messages[-1].get("role") == "tool":
            return jsonr({"summary": "今天按七成练"})
        return jsonr({"summary": "恢复不够，今天的训练按六到八成进行，饮食暂时不调整。"})

    got = asyncio.run(review.run("42", dp, FakeLLM(answer), force=True))
    assert asked.count(review.NUDGE) == 1 and [d.type for d in got.done] == ["today"]
    calm, _ = model(summary="都正常，饮食暂时不调整，不用减量")
    asyncio.run(review.run("42", dp, calm, force=True))
    assert all(review.NUDGE not in str(m[1][-1]["content"]) for m in calm.seen)  # 说不调的不提醒


# ---- 独立审查（11-03）提的问题 ----------------------------------------------------------------


def _propose(dp: Any, stage: Any) -> Any:
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe, today=stage))
    f = facts_id(seen, "当前计划")
    op = {"kind": "swap", "day": TODAY.isoweekday(), "exercise": "杠铃深蹲", "to": "高脚杯深蹲"}
    llm, _ = model({"type": "plan", "why": "膝盖不舒服先换", "basis": [f], "ops": [op],
                    "check": {"metric": "completion", "op": ">=", "value": 80, "days": 7}})  # fmt: skip
    return asyncio.run(review.run("42", dp, llm, force=True, today=stage))


def test_a_proposal_is_not_an_applied_adjustment() -> None:
    """第 1 条：提的改计划在调整经历里记成"待确认"：管家消息不当成已经生效的列出来，不核对预期，不进阶段小结。"""
    from ironm_agent.coach_state import unseen

    dp = setup()
    stage = TODAY + timedelta(days=28)
    _propose(dp, stage)
    state = asyncio.run(dp.store.get("42"))
    hist = asyncio.run(dp.store.history("42"))
    mine = [c for c in hist if c.key == "review:propose"]
    assert mine and mine[0].status == "confirm"
    assert all(c.key != "review:propose" for c in unseen(state, hist))  # 不在"已经调整"里再列一次
    later, seen = model()
    asyncio.run(review.run("42", dp, later, today=stage + timedelta(days=8)))
    assert "建议这样改计划" not in seen[0]  # 没执行的不核对、不当成以前调整的效果
    after = [c for c in asyncio.run(dp.store.history("42")) if c.key == "review:propose"]
    assert any(c.check for c in after) and not any(c.result for c in after)  # 到期了也不去核对它


def test_chat_edits_do_not_merge_into_the_checkup_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    """第 2 条：复查存的预览不是这段对话给的：对话里改计划不在它上面接着改。"""
    from ironm_agent.actions import PLAN_EDIT
    from tests.fakes import acting
    from tests.test_single_agent import cards, single
    from tests.test_turn_flow import run

    a, _ = single(acting(PLAN_EDIT, {"ops": [{"kind": "move", "day": 3, "to_day": 4}]}, {"answer": "好〔经验〕。"}),
                  monkeypatch, seeded=True, old=True)  # fmt: skip
    asyncio.run(a._training.add_draft("42", "plan", {"plan": asyncio.run(a._training.plan("42")).plan.model_dump(mode="json"),
                                                     "changes": "复查的", "source": "checkup"}))  # fmt: skip

    async def told(*_: str) -> list[str]:
        return ["用户：你好", "教练（要点）：你好"]

    a._history = told
    blocks, seen = run(a, "把周三挪到周四")
    assert cards(blocks) and not seen["plan_ops"]["merged"]


def test_two_kcal_changes_in_one_checkup_undo_back_to_none() -> None:
    """第 3 条：同一轮调两次热量，撤销回到没调的样子。"""
    dp = setup()
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe))
    f = facts_id(seen, "每日热量目标")
    llm, _ = model({"type": "kcal", "delta": -150, "why": "a", "basis": [f]},
                   {"type": "kcal", "delta": -100, "why": "b", "basis": [f]})  # fmt: skip
    got = asyncio.run(review.run("42", dp, llm, force=True))
    assert [d.why for d in got.done] == ["b"] and asyncio.run(dp.diet.current("42")).kcal == -100  # type: ignore[union-attr]
    asyncio.run(review.undo("42", dp, "review:kcal"))
    assert asyncio.run(dp.diet.current("42")) is None


def test_undoing_a_confirmed_proposal_restores_the_plan() -> None:
    """第 4 条：他确认了复查的预览、又说不用这样调：计划恢复上一版。"""
    dp = setup()
    stage = TODAY + timedelta(days=28)
    got = _propose(dp, stage)
    asyncio.run(dp.training.confirm("42", str(got.done[0].value["draft"])))

    def names() -> list[str]:
        stored = asyncio.run(dp.training.plan("42"))
        assert stored is not None
        return [x.exercise for s in stored.plan.sessions for x in s.items]

    assert "高脚杯深蹲" in names()
    assert asyncio.run(review.undo("42", dp, "review:propose", today=stage)) is not None
    assert "杠铃深蹲" in names() and "高脚杯深蹲" not in names()


def test_a_stale_proposal_is_not_served_after_the_plan_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """第 5 条：早上复查提的预览，中午计划又改过了：晚上点"确认，出方案"不再给它（会整份覆盖新计划）。"""
    from ironm_agent import web_more
    from ironm_agent.training import plan_content
    from tests.test_coach import plan_today

    dp = setup()
    stage = TODAY + timedelta(days=28)
    got = _propose(dp, stage)
    newer = asyncio.run(dp.training.add_draft("42", "plan", plan_content(plan_today(), "中午改的")))
    asyncio.run(dp.training.confirm("42", newer.id))
    monkeypatch.setattr(web_more, "coach_deps", lambda: dp)
    monkeypatch.setattr(web_more, "date", type("D", (), {"today": staticmethod(lambda: stage)}))
    out = asyncio.run(web_more._checkup_proposal("42", dp.training))
    assert out is not None and out["status"] == "no_change"
    assert (
        asyncio.run(dp.training.draft("42", str(got.done[0].value["draft"]))).state == "cancelled"
    )  # type: ignore[union-attr]
    from ironm_agent.coach_state import pending

    asks = pending(asyncio.run(dp.store.get("42")), stage)  # type: ignore[arg-type]
    assert all(x.key != "review:propose" for x in asks)  # 这条待确认也收起来了（复核 11-03）


def test_concurrent_first_opens_run_the_checkup_once() -> None:
    """第 6 条：打开对话和第一次提问同时触发：只跑一次，不重复调热量。"""
    dp = setup()
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe))
    f = facts_id(seen, "每日热量目标")
    day = TODAY + timedelta(days=1)
    calls: list[int] = []

    def answer(stage: Any, messages: Any, tools: Any) -> Any:
        calls.append(1)
        if tools and not any(m.get("role") == "tool" for m in messages):
            return call("propose_kcal_change", delta=-150, why="a", basis=[f])
        return jsonr({"summary": "x"})

    class Slow:  # 真的会让出：两次复查才可能交错
        async def chat(
            self, stage: Any, messages: Any, *, tools: Any = None, json_mode: bool = False
        ) -> Any:
            await asyncio.sleep(0.01)
            return answer(stage, messages, tools)

    async def both() -> None:
        await asyncio.gather(
            review.run("42", dp, Slow(), today=day), review.run("42", dp, Slow(), today=day)
        )

    asyncio.run(both())
    assert len(calls) == 2  # 一次复查：调工具一次、作答一次


def test_tool_calls_on_the_last_round_are_not_executed(monkeypatch: pytest.MonkeyPatch) -> None:
    """第 8 条：最后一轮没给工具它还要调：不执行，按它写的作答。"""
    dp = setup()
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe))
    f = facts_id(seen, "当前计划")

    def answer(stage: Any, messages: Any, tools: Any) -> Any:
        if not tools:  # 最后一轮没给工具，它还要调另一样
            return call("coach_note", kind="note", text="早点睡", why="x", basis=[f])
        return call("adjust_today", ratio=0.6, why="x", basis=[f])  # 一直调

    got = asyncio.run(review.run("42", dp, FakeLLM(answer), force=True))
    assert [d.type for d in got.done] == [
        "today"
    ]  # 前面那次生效；最后一轮的没执行（同一项也不会被它换掉）
    assert asyncio.run(dp.store.get("42")).review.day == TODAY  # type: ignore[union-attr]


def test_locked_tools_say_so() -> None:
    """平时没有改计划、不到 14 天没有调热量：是锁着，不是校验没过。"""
    dp = setup()
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe))
    f = facts_id(seen, "当前计划")
    llm, _ = model(
        {"type": "plan", "why": "x", "basis": [f], "ops": [{"kind": "reduce", "ratio": 0.7}]}
    )
    asyncio.run(review.run("42", dp, llm, force=True))
    results = [str(m["content"]) for _, msgs in llm.seen for m in msgs if m.get("role") == "tool"]
    assert results and "没到复查它的时候" in results[0]


def test_says_adjust_reads_negations_and_more_wordings() -> None:
    for t in (
        "今天按六到八成练",
        "强度降到七成",
        "今天练 70%",
        "热量下调 150",
        "建议减 200 千卡",
        "按 0.7 练",
        "今天休息",
        "睡眠不足今天按七成练",  # 原因里的"不/没"不算否定（复核 11-03）
        "恢复不好今天减量",
        "心率没回落今天休息一天",
    ):
        assert review.says_adjust(t), t
    for t in (
        "不用减量",
        "无需减量",
        "不要减量",
        "不必少吃",
        "今天休息日",
        "暂时不需要调整为别的",
        "都正常",
    ):
        assert not review.says_adjust(t), t


def test_an_earlier_chat_preview_under_a_checkup_draft_still_merges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """复核：取预览时就跳过复查的，不压住这段对话更早给的那张（不然第一处修改会丢）。"""
    from ironm_agent.actions import PLAN_EDIT
    from tests.test_single_agent import cards, single
    from tests.test_turn_flow import run

    ops = {"q": [{"kind": "move", "day": 3, "to_day": 4}]}

    def answer(system: str, user: str, results: list[str]) -> Any:
        return jsonr({"answer": "好〔经验〕。"}) if results else call(PLAN_EDIT, ops=ops["q"])

    a, _ = single(answer, monkeypatch, seeded=True, old=True)
    first, _ = run(a, "把周三挪到周四")
    d1 = cards(first)[0].removeprefix("card-")
    plan = asyncio.run(a._training.plan("42"))
    assert plan is not None
    asyncio.run(a._training.add_draft("42", "plan", {"plan": plan.plan.model_dump(mode="json"),
                                                     "changes": "复查的", "source": "checkup"}))  # fmt: skip

    async def told(*_: str) -> list[str]:
        return ["用户：把周三挪到周四", "教练（要点）：好"]

    a._history = told
    ops["q"] = [{"kind": "remove", "day": 5}]
    second, seen = run(a, "再把周五删掉")
    assert seen["plan_ops"]["merged"] and cards(second)
    assert a._training._drafts["42"][d1].state == "cancelled"  # 接着第一张改，第一张作废


def test_second_kcal_failure_restores_the_first_and_undo_goes_back_to_before() -> None:
    """复核：之前已经有饮食页的调整；同一轮第二次调热量没通过：第一次补回，撤销回到饮食页那次。"""
    from ironm_agent.metrics import KcalAdjust

    dp = setup()
    asyncio.run(dp.diet.apply("42", KcalAdjust(-200, TODAY - timedelta(days=20), "饮食页")))
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe))
    f = facts_id(seen, "每日热量目标")
    llm, _ = model({"type": "kcal", "delta": -150, "why": "a", "basis": [f]},
                   {"type": "kcal", "delta": -100, "why": "b", "basis": ["F999"]})  # fmt: skip
    got = asyncio.run(review.run("42", dp, llm, force=True))
    assert [d.why for d in got.done] == ["a"] and asyncio.run(dp.diet.current("42")).kcal == -350  # type: ignore[union-attr]
    asyncio.run(review.undo("42", dp, "review:kcal"))
    assert asyncio.run(dp.diet.current("42")).kcal == -200  # type: ignore[union-attr]


def test_a_second_proposal_is_given_when_the_first_was_handled(monkeypatch: pytest.MonkeyPatch) -> None:
    """复核 11-05：一天有改计划、临时调整两份时，第一份处理过了照样给第二份，并说还剩几份。"""
    from ironm_agent import web_more
    from ironm_agent.coach_state import Done, Review
    from ironm_agent.training import plan_content

    dp = setup()
    base = asyncio.run(dp.training.plan("42"))
    assert base is not None
    plan = asyncio.run(dp.training.add_draft("42", "plan", {**plan_content(base.plan), "base": base.id}))
    temp = asyncio.run(dp.training.add_draft("42", "temp", {"temp": {"start": TODAY.isoformat(), "end": TODAY.isoformat(),
                                                                    "ops": []}, "base": base.id}))  # fmt: skip
    done = [Done(key="review:propose", type="propose", title="改计划", why="a", basis="F1", value={"draft": plan.id}),
            Done(key="review:temp", type="propose", title="临时调整", why="b", basis="F1", value={"draft": temp.id})]  # fmt: skip
    state = asyncio.run(dp.store.get("42"))
    if state is None:
        from ironm_agent.coach_state import evaluate

        state, _ = asyncio.run(evaluate("42", dp, reason="x", today=TODAY))
    asyncio.run(dp.store.save("42", state.model_copy(update={"review": Review(day=TODAY, done=done)}), []))
    monkeypatch.setattr(web_more, "coach_deps", lambda: dp)
    monkeypatch.setattr(web_more, "date", type("D", (), {"today": staticmethod(lambda: TODAY)}))
    first = asyncio.run(web_more._checkup_proposal("42", dp.training))
    assert first is not None and first["draft"]["id"] == plan.id and first["more"] == 1
    asyncio.run(dp.training.cancel("42", plan.id))
    second = asyncio.run(web_more._checkup_proposal("42", dp.training))
    assert second is not None and second["status"] == "ok" and second["draft"]["id"] == temp.id
    assert second["more"] == 0
