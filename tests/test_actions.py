"""动作改成工具，跟着规程一起装（spec [2026-10-23] §120 第 1 批：训练）。

整轮走一遍用假模型；不连数据库、不调用真实模型。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from ironm_agent.actions import (
    ASK_TERMS,
    LOG_WORKOUT,
    MAX_ACTIONS,
    NEW_PLAN,
    NOT_DONE,
    NUDGE_CLAIM,
    PLAN_EDIT,
    Desk,
    Outcome,
    claimed,
    claims,
)
from ironm_agent.llm import Reply
from ironm_agent.skills import by_id
from tests.fakes import acting, call, jsonr
from tests.test_plugin import text_of
from tests.test_single_agent import BP, NEW, cards, single
from tests.test_turn_flow import TODAY, run, snapshot_of

MOVE = [{"kind": "move", "day": 3, "to_day": 4, "why": "你要求的"}]
DROP_FRI = [{"kind": "remove", "day": 5, "why": "你要求的"}]


def _toolset(skill: str) -> tuple[str, ...]:
    x = by_id(skill)
    assert x is not None
    return x.toolset


def _desk(**kw: Any) -> Desk:
    async def ok(desk: Desk, args: Any) -> Outcome:
        return Outcome(True, "已出预览。", kind="plan", draft=str(args.get("n", "d")))

    handlers = {PLAN_EDIT: ok, NEW_PLAN: ok, LOG_WORKOUT: ok}
    return Desk(kw.pop("handlers", handlers), **kw)


def test_action_tools_come_with_their_skill() -> None:
    d = _desk(has_plan=True)
    assert d.unlock(_toolset("data-read")) == [] and d.schemas() == []  # 没装就没有
    assert set(d.unlock(_toolset("plan-build"))) == {PLAN_EDIT, NEW_PLAN, ASK_TERMS}
    assert d.unlock(_toolset("log-review")) == [LOG_WORKOUT]
    no_plan = _desk(has_plan=False)
    assert no_plan.unlock(_toolset("plan-build")) == [NEW_PLAN, ASK_TERMS]  # 没有计划时没有改计划


def test_data_risk_turn_has_no_plan_tools_but_can_still_log(monkeypatch: Any) -> None:
    a, s = single(lambda *_: jsonr({"answer": "好。"}), monkeypatch, seeded=True, old=True,
                  snapshot=snapshot_of(BP))  # fmt: skip
    run(a, "帮我排个计划")
    offered = s.system.split("需要信息就调用工具（")[1].split("）")[0]  # 这一轮给它的工具
    assert "plan_templates" in offered and PLAN_EDIT not in offered and NEW_PLAN not in offered
    from ironm_agent.constraints import Context
    from tests.test_plan_ops import plan as seeded_plan
    from tests.test_protools_wiring import ctx

    handlers = a._action_handlers("42", "x", seeded_plan(), Context(), TODAY, {}, ctx(),
                                  confirmed=True, merge=False, blocked=True)  # fmt: skip
    assert set(handlers) == {LOG_WORKOUT}  # 拦下时只给记训练（和原来一样）


def test_edit_tool_previews_and_the_answer_matches_the_card(monkeypatch: Any) -> None:
    got: list[str] = []

    def answer(system: str, user: str, results: list[str]) -> Reply:
        if not results:
            return call(PLAN_EDIT, ops=MOVE)
        got.extend(results)
        return jsonr({"answer": "周三那次挪到周四了。"})

    a, _ = single(answer, monkeypatch, seeded=True, old=True)
    blocks, seen = run(a, "把周三挪到周四")
    assert got[0].startswith("已出预览") and "周三" in got[0]  # 改了什么当场告诉它
    assert len(cards(blocks)) == 1 and seen["action"] == "edit" and seen["preview"] == "plan"
    assert seen["actions"] == [{"tool": PLAN_EDIT, "result": "ok"}]


def test_rejected_edit_goes_back_to_the_agent_and_a_fixed_one_previews(monkeypatch: Any) -> None:
    clash = [
        {"kind": "remove", "day": 5},
        {"kind": "edit", "day": 5, "exercise": "臀桥", "sets": 4},
    ]
    got: list[str] = []

    def answer(system: str, user: str, results: list[str]) -> Reply:
        got[:] = results
        if not results:
            return call(PLAN_EDIT, ops=clash)  # 删掉周五又改周五：矛盾
        if len(results) == 1:
            return call(PLAN_EDIT, ops=DROP_FRI)  # 看了原因，改了再交
        return jsonr({"answer": "周五那次先删了。"})

    a, _ = single(answer, monkeypatch, seeded=True, old=True)
    blocks, seen = run(a, "周五删掉，再把周五的臀桥改 4 组")
    assert "没出预览" in got[0] and got[1].startswith("已出")
    assert len(cards(blocks)) == 1 and [x["result"] for x in seen["actions"]] == ["rejected", "ok"]


def test_rejected_edit_without_retry_gives_no_card_and_says_why(monkeypatch: Any) -> None:
    clash = [
        {"kind": "remove", "day": 5},
        {"kind": "edit", "day": 5, "exercise": "臀桥", "sets": 4},
    ]

    def answer(system: str, user: str, results: list[str]) -> Reply:
        if not results:
            return call(PLAN_EDIT, ops=clash)
        return jsonr({"answer": "你是想删掉周五，还是改周五的臀桥？分开说一条。"})

    a, _ = single(answer, monkeypatch, seeded=True, old=True)
    blocks, seen = run(a, "周五删掉，再把周五的臀桥改 4 组")
    assert not cards(blocks) and "分开说" in text_of(blocks) and seen["action"] == "none"


def test_two_edits_in_one_turn_leave_only_the_last_preview(monkeypatch: Any) -> None:
    def answer(system: str, user: str, results: list[str]) -> Reply:
        if not results:
            return call(PLAN_EDIT, ops=MOVE)
        if len(results) == 1:
            return call(PLAN_EDIT, ops=DROP_FRI)
        return jsonr({"answer": "周三挪到周四，周五也删了。"})

    a, _ = single(answer, monkeypatch, seeded=True, old=True)
    blocks, seen = run(a, "把周三挪到周四，周五删掉")
    shown = cards(blocks)
    assert len(shown) == 1 and seen["plan_ops"]["merged"]  # 在上一张上接着改
    store = a._training
    draft = asyncio.run(store.draft("42", shown[0].removeprefix("card-")))
    assert {x["kind"] for x in draft.content["ops"]} == {"move", "remove"}
    pending = [d for d in store._drafts["42"].values() if d.state == "pending"]
    assert len(pending) == 1  # 前一张作废了


def test_action_calls_are_capped_per_turn() -> None:
    d = _desk(has_plan=True)
    d.unlock(_toolset("plan-build"))
    said = [asyncio.run(d.run(NEW_PLAN, {"n": str(i)})) for i in range(MAX_ACTIONS + 1)]
    assert all(x.startswith("已出") for x in said[:MAX_ACTIONS]) and "不能再交" in said[-1]
    assert d.stale == ["0", "1", "2"]  # 同一轮被后一张换掉的要作废


def test_action_calls_do_not_use_up_the_query_limit() -> None:
    from ironm_agent.experts import MAX_QUERIES, _loop
    from ironm_agent.kb import default_kb
    from ironm_agent.roles import GENERAL
    from ironm_agent.tools import Toolbox
    from tests.fakes import FakeLLM

    box = Toolbox(GENERAL, kb=default_kb(), health=None, user_id="42", session_id="s")
    box.actions = _desk(has_plan=True)
    box.actions.unlock(_toolset("plan-build"))
    box.evidence.knowledge_queries = MAX_QUERIES  # 查询次数已经用完
    replies = iter([call(PLAN_EDIT, ops=MOVE), jsonr({"answer": "周三挪到周四了〔经验〕。"})])
    llm = FakeLLM(lambda *_: next(replies))
    msgs: list[dict[str, Any]] = [
        {"role": "system", "content": "x"},
        {"role": "user", "content": "y"},
    ]
    opinion = asyncio.run(_loop(GENERAL, msgs, box, llm, "把周三挪到周四", ("answer",)))
    assert box.actions.plan is not None and opinion.speak
    assert not any("查询次数已用完" in str(m.get("content")) for m in msgs)


def test_claiming_a_change_without_a_tool_call_is_nudged_then_removed(monkeypatch: Any) -> None:
    lasts: list[str] = []

    def answer(system: str, user: str, results: list[str]) -> Reply:
        lasts.append(s.last)
        return jsonr({"answer": "已经把周三挪到周四了。下周照这个练。"})

    a, s = single(answer, monkeypatch, seeded=True, old=True)
    blocks, seen = run(a, "把周三挪到周四")
    assert NUDGE_CLAIM in lasts  # 提醒了一次
    assert seen["_experts"][0]["nudged"] and seen["unacted"] and not cards(blocks)
    assert "已经把" not in text_of(blocks) and "下周照这个练" in text_of(blocks)


def test_claim_after_nudge_that_is_all_claim_says_it_was_not_done() -> None:
    d = _desk(has_plan=True)
    assert d.followup("记下了。") == NUDGE_CLAIM and d.followup("记下了。") is None  # 只提醒一次
    assert d.settle("记下了。") == NOT_DONE and d.unacted


def test_claim_wording() -> None:
    for said in ("已经把周三挪到周四了。", "记下了，下次试 62.5 公斤。", "按你说的改好了。",
                 "周三的侧平举换成俯卧撑了。", "给你排好了。", "我已经按你说的调了一下。",
                 "卧推我给你换了个哑铃版。",
                 # 复核新问题 C：后面那句是建议、问句、否定，前面说已经改了照样算
                 "已经记下了，下次可以加到62.5公斤。", "已经把周三挪到周四了，没动别的。",
                 "按你说的改好了，周四别练太重。", "已经帮你把卧推换成哑铃卧推了，如果肩还疼就停。",
                 "改好了，你看看卡片对不对？", "记下了，这次比上次多了一组。", "已经记下了，原来的计划不变。",
                 "已经把计划里周三的深蹲换成腿举了。"):  # fmt: skip
        assert claims(said), said
    for said in ("可以把深蹲换成腿举。", "换成腿举就好了。", "建议挪到周四。", "你上次深蹲 60 公斤做了 8 次。",
                 "膝盖疼的话先别做深蹲，换成腿举更合适。", "要不要我帮你记下这次训练？",
                 "我可以帮你调整好计划吗？", "需要的话我可以帮你排好一份新计划。", "体重已经稳定，不用改了。",
                 "这周先不用减到3组了。", "可以先把深蹲换成腿举了。",
                 # 复核新问题 D：主语是他
                 "你最近已经换了两次分化，先稳定一段。", "你的作息已经调了过来。", "你已经排了三周的训练。",
                 "你已经记下了每组的重量。"):  # fmt: skip
        assert not claims(said), said  # 问句、提议、否定、说以前的事、主语是他都不算
    assert claimed("记下了，下次加重。周三挪到周四了。") == {"log", "plan"}


def test_prompt_and_answer_have_no_json_actions_left() -> None:
    from ironm_agent import agent, experts

    text = agent._PROMPT + agent.actions_prompt(has_plan=True, confirmed=True, just_asked=True)
    for old in ('"plan"', '"ops"', '"log"', '"action"', '"busy"', '"scope"'):
        assert old not in text, old
    assert PLAN_EDIT in text and NEW_PLAN in text and LOG_WORKOUT in text
    assert not hasattr(experts, "write_task") and not hasattr(experts, "TASKS")
    assert {"plan", "ops", "log", "action"}.isdisjoint(experts.Opinion.model_fields)


def test_log_tool_previews_and_keeps_only_his_numbers(monkeypatch: Any) -> None:
    log = {"day": "", "session": "", "done": True, "items": [
        {"exercise": "深蹲", "sets": 5, "reps": "5", "weight_kg": 80, "done_sets": []}]}  # fmt: skip
    a, _ = single(acting(LOG_WORKOUT, log, {"answer": "练得不错〔经验〕。"}), monkeypatch, old=True)
    blocks, seen = run(a, "今天练了深蹲 5 组 5 次 60 公斤")  # 他说的是 60，模型写成 80
    assert seen["action"] == "log" and cards(blocks)
    draft = asyncio.run(a._training.draft("42", cards(blocks)[0].removeprefix("card-")))
    assert draft.content["log"]["items"][0]["weight_kg"] != 80  # 不是他说的数不记


def test_new_plan_needs_confirmed_terms_only_when_it_is_new(monkeypatch: Any) -> None:
    a, _ = single(acting(NEW_PLAN, {"plan": NEW, "changes": "换成三练", "kind": "rewrite"},
                         {"answer": "换成三练全身〔经验〕。"}), monkeypatch, seeded=True, old=True)  # fmt: skip
    blocks, seen = run(a, "把训练改成三练全身")
    assert cards(blocks) and seen["path"] != "clarify"  # 在现有计划上换分化：不用先确认
    a, _ = single(acting(NEW_PLAN, {"plan": NEW, "changes": "新排", "kind": "new"},
                         {"answer": "好，先确认一下条件。"}), monkeypatch, seeded=True, old=True)  # fmt: skip
    blocks, seen = run(a, "我想重新要一份计划")
    assert not cards(blocks) and seen["path"] == "clarify"  # 新排一份：先确认条件


def test_logs_only_have_tool_names_and_results(
    monkeypatch: Any, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="ironm_agent.actions")
    a, _ = single(acting(PLAN_EDIT, {"ops": MOVE}, {"answer": "好〔经验〕。"}), monkeypatch,
                  seeded=True, old=True)  # fmt: skip
    run(a, "把周三挪到周四")
    lines = [r.getMessage() for r in caplog.records if r.name == "ironm_agent.actions"]
    assert lines == [f"action: tool={PLAN_EDIT} result=ok"]


def test_asking_for_terms_is_marked_by_a_tool_and_falls_back_to_the_fixed_list(
    monkeypatch: Any,
) -> None:
    """真实模型回放（11-03）：它自己问了条件、开头没那句也没交计划，下一轮认不出问过了；
    改成先调用 ask_plan_terms 标记，没写好开头时退回系统列的五项。"""
    from ironm_agent.clarify import HEAD

    a, _ = single(acting(ASK_TERMS, {}, {"answer": "先定个数和日期：想减到多少公斤？"}, tries=1), monkeypatch,
                  old=True)  # fmt: skip
    blocks, seen = run(a, "我想要更好的减重，给我一份计划吗")
    assert seen["path"] == "clarify" and seen["clarify_by"] == "fixed"
    assert text_of(blocks).startswith(HEAD) and not cards(blocks)
    assert seen["actions"] == [{"tool": ASK_TERMS, "result": "ok"}]


def test_new_user_cannot_skip_the_terms_by_calling_it_a_rewrite(monkeypatch: Any) -> None:
    """独立审查第 1 条：没有计划时交 kind=rewrite 也要先确认条件。"""
    a, _ = single(acting(NEW_PLAN, {"plan": NEW, "changes": "", "kind": "rewrite"},
                         {"answer": "好，先确认一下条件。"}), monkeypatch, old=True)  # fmt: skip
    blocks, seen = run(a, "给我一份训练计划")
    assert seen["path"] == "clarify" and not cards(blocks)


def test_last_turns_preview_survives_a_turn_that_fails_to_answer(monkeypatch: Any) -> None:
    """独立审查第 3 条：这一轮在上一张上接着改、却没答出来：上一张还能确认，这一轮的作废。"""
    state = {"turn": 1}

    def answer(system: str, user: str, results: list[str]) -> Reply:
        if not results:
            return call(PLAN_EDIT, ops=MOVE if state["turn"] == 1 else DROP_FRI)
        if state["turn"] == 1:
            return jsonr({"answer": "周三那次挪到周四了。"})
        return Reply("不是 JSON")  # 第二轮答不出来

    a, _ = single(answer, monkeypatch, seeded=True, old=True)
    first, _ = run(a, "把周三挪到周四")
    p = cards(first)[0].removeprefix("card-")

    async def told(*_: str) -> list[str]:
        return ["用户：把周三挪到周四", "教练（要点）：周三那次挪到周四了"]

    a._history = told
    state["turn"] = 2
    second, seen = run(a, "再把周五删掉")
    assert seen["path"] == "no_answer" and not cards(second)
    drafts = a._training._drafts["42"]
    assert drafts[p].state == "pending"  # 上一张还能确认
    assert all(d.state == "cancelled" for k, d in drafts.items() if k != p)  # 这一轮的作废


def test_new_preview_retires_last_turns_one_only_after_it_is_shown(monkeypatch: Any) -> None:
    state = {"ops": MOVE}

    def answer(system: str, user: str, results: list[str]) -> Reply:
        return jsonr({"answer": "好〔经验〕。"}) if results else call(PLAN_EDIT, ops=state["ops"])

    a, _ = single(answer, monkeypatch, seeded=True, old=True)
    first, _ = run(a, "把周三挪到周四")

    async def told(*_: str) -> list[str]:
        return ["用户：把周三挪到周四", "教练（要点）：好"]

    a._history = told
    state["ops"] = DROP_FRI
    second, _ = run(a, "再把周五删掉")
    drafts = a._training._drafts["42"]
    assert drafts[cards(first)[0].removeprefix("card-")].state == "cancelled"
    assert drafts[cards(second)[0].removeprefix("card-")].state == "pending"


def test_risk_fallback_drops_a_workout_log_it_did_not_show(monkeypatch: Any) -> None:
    """独立审查第 4 条：危急情况退回固定回答时，这一轮记训练的预览也作废。"""
    log = {"items": [{"exercise": "深蹲", "sets": 5, "reps": "5", "weight_kg": 60}], "done": True}
    a, _ = single(acting(LOG_WORKOUT, log, {"answer": "记下了，明天练上肢〔经验〕。"}), monkeypatch,
                  old=True, snapshot=snapshot_of(BP))  # fmt: skip
    blocks, seen = run(a, "今天练了深蹲 5 组 5 次 60 公斤，明天练什么")
    assert seen["path"] == "risk" and not cards(blocks)
    left = list(a._training._drafts.get("42", {}).values())
    assert left and all(d.state == "cancelled" for d in left)  # 建过、作废了


def test_a_logged_workout_does_not_cover_a_plan_change_that_was_not_made(monkeypatch: Any) -> None:
    """独立审查第 6 条：记训练成功、改计划没成，说"周三换成腿举了"那句照样要提醒、去掉。"""
    log = {"items": [{"exercise": "深蹲", "sets": 5, "reps": "5", "weight_kg": 60}], "done": True}
    a, _ = single(acting(LOG_WORKOUT, log, {"answer": "记下了这次深蹲。周三的深蹲换成腿举了。"}),
                  monkeypatch, seeded=True, old=True)  # fmt: skip
    blocks, seen = run(a, "今天练了深蹲 5 组 5 次 60 公斤，周三的深蹲换成腿举")
    assert seen["_experts"][0]["nudged"] and seen["unacted"] and len(cards(blocks)) == 1
    assert "换成腿举了" not in text_of(blocks) and "记下了这次深蹲" in text_of(blocks)


def test_previews_not_sent_before_a_disconnect_are_retired(monkeypatch: Any) -> None:
    """复核新问题 A：卡片还没发出去他就断开了：这一轮存下的预览作废，下一轮不会接着它改。"""
    a, _ = single(acting(PLAN_EDIT, {"ops": MOVE}, {"answer": "周三那次挪到周四了。"}), monkeypatch,
                  seeded=True, old=True)  # fmt: skip
    a._observe, a._remember_on = (lambda _: None), False

    async def go() -> None:
        stream = a.generate_response("42", [{"role": "user", "content": "把周三挪到周四"}],
                                     session_id="42:s1")  # fmt: skip
        async for b in stream:
            if b.get("type") == "tool_result" and b.get("tool_call_id") == "agent":
                break  # 管家答完、卡片还没发：断开
        await stream.aclose()
        await a.settle()

    asyncio.run(go())
    left = list(a._training._drafts["42"].values())
    assert left and all(d.state == "cancelled" for d in left)


def test_asking_terms_again_right_after_he_confirmed_is_turned_into_a_plan(
    monkeypatch: Any,
) -> None:
    """真实模型回放（11-03）：他回了"按这个排"，它又调 ask_plan_terms 再问一遍；系统让它交计划。"""
    from ironm_agent.clarify import HEAD

    got: list[str] = []

    def answer(system: str, user: str, results: list[str]) -> Reply:
        got[:] = results
        if not results:
            return call(ASK_TERMS)
        if len(results) == 1:
            return call(NEW_PLAN, plan=NEW, changes="三练全身", kind="new")
        return jsonr({"answer": "按你确认的排了三练全身〔经验〕。"})

    a, _ = single(answer, monkeypatch, old=True)

    async def asked(*_: str) -> list[str]:
        return ["用户：给我一份训练计划", f"教练（要点）：{HEAD}：目标、场景、器械、时间、伤病……"]

    a._history = asked
    blocks, seen = run(a, "按这个排")
    assert "算确认，不要再问一遍" in got[0] and cards(blocks) and seen["path"] != "clarify"
    assert seen["actions"][0] == {"tool": ASK_TERMS, "result": "confirmed"}


def test_plan_sent_back_by_the_check_is_previewed_if_it_never_comes_back(monkeypatch: Any) -> None:
    """真实模型回放（11-03）：检查没过退回后它一直在查、没再交，原来照出预览，现在也照出（§12）。"""
    from tests.test_protools_wiring import _plan_json

    too_long = _plan_json(
        45, [("高脚杯深蹲", 4), ("哑铃卧推", 4), ("单臂哑铃划船", 4), ("哑铃推举", 4)]
    )
    a, _ = single(acting(NEW_PLAN, {"plan": too_long, "changes": "三练", "kind": "rewrite"},
                         {"answer": "排了三练全身〔经验〕。"}, tries=1), monkeypatch, seeded=True, old=True)  # fmt: skip
    blocks, seen = run(a, "把训练改成三练全身")
    assert [x["result"] for x in seen["actions"]] == ["check", "fallback"]
    assert cards(blocks) and seen["plan_check"] == "partly"


def test_terms_tool_is_offered_on_training_turns_without_plan_build(monkeypatch: Any) -> None:
    """真实模型回放（11-03）：路由没选排训练计划时它手边没有先确认条件的工具，只能自己问、认不出来。"""
    from tests.test_skill_route import routed

    a, s = single(lambda *_: jsonr({"answer": "好。"}), monkeypatch, old=True)
    s.route = routed(["readiness-adjust"], ["train"])
    run(a, "今天练什么")
    offered = s.system.split("需要信息就调用工具（")[1].split("）")[0]
    assert ASK_TERMS in offered and NEW_PLAN not in offered  # 先确认条件的给，交计划的跟着规程
    a, s = single(lambda *_: jsonr({"answer": "你好！"}), monkeypatch, old=True)
    run(a, "你好")
    assert ASK_TERMS not in s.system.split("需要信息就调用工具（")[1].split("）")[0]  # 闲聊不给
