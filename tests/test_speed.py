"""回答提速第二轮（spec [2026-10-23] §165）。不连数据库、不调用真实模型。"""

from __future__ import annotations

from typing import Any

from ironm_agent.checks import autocite, check_text
from ironm_agent.harness import problem_kinds
from ironm_agent.kb import default_kb

KB = default_kb()
ENTRIES = {i: KB.get(i) for i in ("K10", "K28", "K29")}


def cite(text: str, **kw: Any) -> str:
    args: dict[str, Any] = {"support": {}, "entries": ENTRIES, "question": "肌酸怎么吃", "calcs": {}}
    return autocite(text, **(args | kw))


def ok(text: str, **kw: Any) -> bool:
    args: dict[str, Any] = {"support": {}, "entries": ENTRIES, "question": "肌酸怎么吃", "calcs": {}}
    return check_text(text, **(args | kw)) == []


def test_numbers_that_match_a_source_get_it_without_asking_the_model() -> None:
    text = "每天 5 克就够〔K10〕。不用先冲击，每天吃 5 克，坚持 4 周左右。"
    got = cite(text)
    assert got == "每天 5 克就够〔K10〕。不用先冲击，每天吃 5 克，坚持 4 周左右。〔K10〕" and ok(got)
    assert not ok(text)  # 原来要退回模型


def test_an_uncited_but_unique_kb_entry_is_used() -> None:
    assert cite("练到还剩 2 次就停。") == "练到还剩 2 次就停。〔K28〕"


def test_ambiguous_or_unmatched_numbers_are_left_for_the_model() -> None:
    both = "大概 3 组。"  # K10、K29 都有 3：可能认错，不补
    assert cite(both) == both
    none = "每周练 6 天。"
    assert cite(none) == none
    marked = "每周练 6 天〔经验〕。"
    assert cite(marked) == marked


def test_calcs_and_a_single_data_row() -> None:
    calcs = {"C1": "每日热量目标约 2225 千卡"}
    assert cite("每天吃到 2225 千卡左右。", calcs=calcs) == "每天吃到 2225 千卡左右。〔C1〕"
    row = cite("你最近静息心率 58 次。", support={"r3": [58.0], "r4": [61.0]})
    assert row == "<statement>你最近静息心率 58 次。<cite>[r3]</cite></statement>"
    assert ok(row, support={"r3": [58.0], "r4": [61.0]})
    two = "你最近静息心率 58 次。"
    assert cite(two, support={"r3": [58.0], "r4": [58.0]}) == two  # 两行都对得上：不补


def test_statements_and_lines_are_kept() -> None:
    text = "<statement>静息心率 58<cite>[r3]</cite></statement>，挺好。\n每天 5 克就行。\n"
    got = cite(text, support={"r3": [58.0]})
    assert got == "<statement>静息心率 58<cite>[r3]</cite></statement>，挺好。\n每天 5 克就行。〔K10〕\n"


def test_uncited_numbers_are_their_own_kind() -> None:
    problems = check_text("每周练 6 天。", support={}, entries={}, question="", calcs={})
    assert problem_kinds(problems) == ["uncited"]
    assert problem_kinds(["输出不是规定格式的 JSON"]) == ["format"]


def test_the_answer_is_not_sent_back_when_code_can_add_the_source(monkeypatch: Any) -> None:
    from ironm_agent.agent import LOAD_SKILL
    from ironm_agent.llm import Reply
    from tests.fakes import call, jsonr
    from tests.test_plugin import text_of
    from tests.test_single_agent import single
    from tests.test_turn_flow import run

    def answer(system: str, user: str, results: list[str]) -> Reply:
        if not results:
            return call(LOAD_SKILL, id="plan-build")
        return jsonr({"answer": "增肌每个肌群每周 10 组以上〔K04〕。刚开始先做到每周 10 组。"})

    a, solo = single(answer, monkeypatch)
    blocks, seen = run(a, "我想长点肉")
    assert "刚开始先做到每周 10 组" in text_of(blocks)
    assert len(solo.stages) == 2 and not seen["_experts"][0]["fixed"]  # 查一次、答一次，没退回
    assert seen["_experts"][0]["autocited"] == 1


def test_a_plain_prose_answer_is_used_as_is(monkeypatch: Any) -> None:
    from ironm_agent.llm import Reply
    from tests.test_plugin import text_of
    from tests.test_single_agent import single
    from tests.test_turn_flow import run

    a, solo = single(lambda *_: Reply("你好！今天想聊训练还是吃的？"), monkeypatch, old=True)
    blocks, seen = run(a, "你好")
    assert "今天想聊训练还是吃的" in text_of(blocks) and len(solo.stages) == 1
    assert not seen["_experts"][0]["fixed"]


def test_after_the_soft_limit_no_more_lookups(monkeypatch: Any) -> None:
    from ironm_agent import experts
    from ironm_agent.llm import Reply
    from tests.fakes import call, jsonr
    from tests.test_single_agent import single
    from tests.test_turn_flow import run

    monkeypatch.setattr(experts, "SOFT_S", -1.0)
    seen_results: list[list[str]] = []

    def answer(system: str, user: str, results: list[str]) -> Reply:
        seen_results.append(results)
        if not results:
            return call("search_exercises", query="深蹲")
        return jsonr({"answer": "先练高脚杯深蹲〔经验〕。"})

    a, _ = single(answer, monkeypatch, old=True)
    _, seen = run(a, "深蹲怎么练")
    assert seen_results[-1] == [experts.LATE] and seen["_experts"][0]["late"]


def test_a_turn_that_runs_too_long_stops_and_says_so(monkeypatch: Any) -> None:
    import asyncio

    from ironm_agent import agent, plugin
    from tests.test_plugin import text_of
    from tests.test_single_agent import single
    from tests.test_turn_flow import run

    async def slow(*a: Any, **k: Any) -> Any:
        await asyncio.sleep(5)

    monkeypatch.setattr(agent, "HARD_S", 0.05)
    monkeypatch.setattr(agent, "_loop", slow)
    a, _ = single(lambda *_: None, monkeypatch, old=True)  # type: ignore[arg-type,return-value]
    blocks, seen = run(a, "深蹲怎么练")
    assert seen["path"] == "no_answer" and plugin.NO_ANSWER in text_of(blocks)
    assert seen["_experts"][0]["timeout"]


def test_several_lookups_in_one_reply_run_together(monkeypatch: Any) -> None:
    import asyncio

    from ironm_agent import tools as tools_mod
    from ironm_agent.llm import Reply
    from tests.fakes import jsonr
    from tests.test_single_agent import single
    from tests.test_turn_flow import run

    live = {"now": 0, "most": 0}
    real = tools_mod.Toolbox._exercises

    async def slow(self: Any, call: Any) -> str:
        live["now"] += 1
        live["most"] = max(live["most"], live["now"])
        await asyncio.sleep(0.01)
        live["now"] -= 1
        return real(self, str(call.arguments.get("query", "")))

    monkeypatch.setattr(tools_mod.Toolbox, "_dispatch", slow)

    def answer(system: str, user: str, results: list[str]) -> Reply:
        if not results:
            from ironm_agent.llm import ToolCall

            return Reply("", tuple(ToolCall(f"c{i}", "search_exercises", {"query": q})
                                   for i, q in enumerate(("深蹲", "卧推", "硬拉"))))  # fmt: skip
        assert len(results) == 3
        return jsonr({"answer": "这三个都能练〔经验〕。"})

    a, _ = single(answer, monkeypatch, old=True)
    _, seen = run(a, "深蹲卧推硬拉怎么练")
    assert live["most"] == 3 and seen["_experts"][0]["parallel"] == 3


def test_a_new_plan_can_be_handed_in_as_a_template_and_changes(monkeypatch: Any) -> None:
    import re

    from ironm_agent.actions import NEW_PLAN
    from ironm_agent.clarify import HEAD
    from ironm_agent.llm import Reply
    from tests.fakes import call, jsonr
    from tests.test_plugin import text_of
    from tests.test_single_agent import cards, single
    from tests.test_turn_flow import run

    picked: dict[str, str] = {}

    def answer(system: str, user: str, results: list[str]) -> Reply:
        if not results:
            return call("plan_templates", level="beginner", goal="muscle", days_per_week=3, minutes=60,
                        place="gym")  # fmt: skip
        if len(results) == 1:
            m = re.search(r"template=([\w-]+)", results[0])
            if m is None:
                return jsonr({"answer": "方案库没有合适的〔经验〕。"})
            picked["id"] = m.group(1)
            return call(NEW_PLAN, template=m.group(1), changes="照方案库排", kind="new")
        return jsonr({"answer": "按方案库的三练排好了〔经验〕。"})

    a, solo = single(answer, monkeypatch)
    first, _ = run(a, "给我一份训练计划")  # 先确认条件

    async def asked(*_: str) -> list[str]:
        return ["用户：给我一份训练计划", "教练（要点）：" + text_of(first)[:200]]

    a._history = asked
    solo.stages.clear()
    blocks, seen = run(a, "按这个排")
    assert picked and seen.get("action") == "plan" and cards(blocks), (seen.get("actions"), HEAD)
    assert len(solo.stages) == 3  # 选方案、交草稿、作答：不用抄整份、不用先检查


def test_an_unknown_template_is_sent_back() -> None:
    from ironm_agent.actions import Desk
    from ironm_agent.plugin import IronMAgent

    plan, why = IronMAgent._from_template(Desk(handlers={}), {"template": "nope"}, None)
    assert plan is None and "plan_templates" in why


def test_steps_are_sent_while_answering_and_timings_are_recorded(monkeypatch: Any) -> None:
    from ironm_agent.llm import Reply
    from tests.fakes import call, jsonr
    from tests.test_single_agent import single
    from tests.test_turn_flow import run

    def answer(system: str, user: str, results: list[str]) -> Reply:
        if not results:
            return call("search_exercises", query="深蹲")
        return jsonr({"answer": "先练高脚杯深蹲〔经验〕。"})

    a, _ = single(answer, monkeypatch, old=True)
    blocks, seen = run(a, "深蹲怎么练")
    order = [(b["type"], b.get("id") or b.get("tool_call_id")) for b in blocks if b["type"] in ("tool_call", "tool_result")]
    assert order.index(("tool_call", "step-1")) < order.index(("tool_result", "step-1")) < order.index(("tool_result", "agent"))
    step = next(b for b in blocks if b.get("id") == "step-1")
    assert step["name"] == "查动作" and step["args"]["任务"] == "深蹲"
    assert "pre_ms" in seen and "route_wait_ms" in seen and seen["calls_ms"][-1].startswith("expert:")
    assert "cache_hit" in seen and "prompt_tokens" in seen


def test_quiet_tools_are_not_shown_as_steps(monkeypatch: Any) -> None:
    from ironm_agent.actions import RECORD_STATE
    from ironm_agent.llm import Reply
    from tests.fakes import call, jsonr
    from tests.test_single_agent import single
    from tests.test_turn_flow import run

    def answer(system: str, user: str, results: list[str]) -> Reply:
        if not results:
            return call(RECORD_STATE, tired=True)
        return jsonr({"answer": "辛苦了，今天怎么了？"})

    a, _ = single(answer, monkeypatch, old=True)
    blocks, _ = run(a, "好累")
    assert not any(str(b.get("id", "")).startswith("step-") for b in blocks)


def test_usage_is_kept_on_the_call_record() -> None:
    import time

    from ironm_agent.llm import _record, load_models

    route = load_models().route("expert")
    r = _record("expert", route, time.perf_counter(), None, (1200, 1024))
    assert (r.prompt, r.cached, r.ok) == (1200, 1024, True)


def test_two_matching_calcs_are_left_alone() -> None:
    calcs = {"C1": "每日热量目标约 2225 千卡", "C2": "上周平均吃了 2225 千卡"}
    assert cite("每天吃到 2225 千卡左右。", calcs=calcs) == "每天吃到 2225 千卡左右。"


def test_chat_keeps_token_usage(monkeypatch: Any) -> None:
    import asyncio

    from ironm_agent import llm as llm_mod

    async def fake(*a: Any, **k: Any) -> Any:
        return llm_mod.Reply("{}"), (900, 640)

    monkeypatch.setattr(llm_mod, "_request", fake)
    turn = llm_mod.TurnLLM(llm_mod.load_models(), {"DEEPSEEK_API_KEY": "x"})
    asyncio.run(turn.chat("expert", [{"role": "user", "content": "hi"}]))
    assert (turn.calls[0].prompt, turn.calls[0].cached) == (900, 640)


def test_a_patched_sentence_also_gets_its_source_from_code(monkeypatch: Any) -> None:
    import json

    from ironm_agent.agent import LOAD_SKILL
    from ironm_agent.llm import Reply
    from tests.fakes import call, jsonr
    from tests.test_single_agent import single
    from tests.test_turn_flow import run

    turns = {"n": 0}

    def answer(system: str, user: str, results: list[str]) -> Reply:
        if not results:
            return call(LOAD_SKILL, id="plan-build")
        turns["n"] += 1
        if turns["n"] == 1:
            return jsonr({"answer": "增肌每个肌群每周 10 组以上〔K04〕。每周练 777 天。"})
        fix = {"fixes": [{"old": "每周练 777 天。", "new": "刚开始先做到每周 10 组。"}]}
        return Reply(json.dumps(fix, ensure_ascii=False))

    a, _ = single(answer, monkeypatch)
    _, seen = run(a, "我想长点肉")
    e = seen["_experts"][0]
    assert e["fixed"] and e["patched"] and not e["repaired"]  # 改的那句出处由代码补上，不用再修


def test_units_must_match_and_data_rows_only_for_sentences_about_him() -> None:
    sup = {"r1": [72.5, 7.0]}
    assert cite("建议每晚睡够 7 小时。", support=sup) == "建议每晚睡够 7 小时。"  # 一般建议不当成他的数据
    assert cite("你昨晚睡了 7 小时。", support=sup) == "<statement>你昨晚睡了 7 小时。<cite>[r1]</cite></statement>"
    listed = cite("- 你最近静息心率 58 次。", support={"r3": [58.0]})
    assert listed == "- <statement>你最近静息心率 58 次。<cite>[r3]</cite></statement>"  # 列表记号留在外面
    assert cite("每天 5 克就够〔K10〕。每周练 5 组。") == "每天 5 克就够〔K10〕。每周练 5 组。"  # 单位对不上：不补
    assert cite("大概 3。") == "大概 3。"  # 没带单位：说不准
    only = {"K10": ENTRIES["K10"]}
    assert cite("大概 3。", entries=only) == "大概 3。"  # 只有一条资料也不补


def test_non_answers_are_not_taken_as_answers() -> None:
    from ironm_agent.experts import _prose

    for junk in ("我先查一下动作库，然后再给你排。", "Error: request failed", "json", "接下来这样安排：",
                 "The answer is not available right now.", "plan_templates(level=beginner)",
                 "Traceback (most recent call last)", "OK"):  # fmt: skip
        assert _prose(junk) is None, junk
    assert _prose("今天先休息，明天再练腿。") == {"answer": "今天先休息，明天再练腿。"}


def test_web_search_is_not_run_alongside_other_lookups() -> None:
    import asyncio

    from ironm_agent.experts import _run_calls
    from ironm_agent.llm import ToolCall

    order: list[str] = []

    class Box:
        class evidence:
            queries = 0

        def is_action(self, name: str) -> bool:
            return False

        async def run(self, call: Any) -> str:
            order.append(f"start {call.name}")
            await asyncio.sleep(0)
            order.append(f"end {call.name}")
            return call.name

    calls = [ToolCall("a", "search_web", {}), ToolCall("b", "search_exercises", {}),
             ToolCall("c", "search_knowledge", {})]  # fmt: skip
    got = asyncio.run(_run_calls(calls, Box(), {}))  # type: ignore[arg-type]
    assert got == ["search_web", "search_exercises", "search_knowledge"]
    web = order.index("start search_web")
    assert order[web + 1] == "end search_web"  # 联网查的那次单独跑，不和别的交错
    late = asyncio.run(_run_calls(calls, Box(), {"late": True}))  # type: ignore[arg-type]
    from ironm_agent.experts import LATE

    assert late == [LATE, LATE, LATE]


def test_template_changes_that_do_not_apply_are_sent_back(monkeypatch: Any) -> None:
    from ironm_agent.actions import Desk
    from ironm_agent.plugin import IronMAgent
    from tests.test_plan_ops import plan

    desk = Desk(handlers={})
    desk.template_plans["t1"] = plan()
    bad = {"template": "t1", "ops": [{"kind": "remove", "day": 1, "exercise": "不存在的动作"}]}
    got, why = IronMAgent._from_template(desk, bad, None)
    assert got is None and "没套上" in why
    half = {"template": "t1", "ops": [{"kind": "remove", "day": 1, "exercise": "提踵"},
                                      {"kind": "remove", "day": 1, "exercise": "不存在的动作"}]}  # fmt: skip
    got, why = IronMAgent._from_template(desk, half, None)
    assert got is None and "不存在的动作" in why  # 套上一半也退回，不悄悄丢掉
    ok, _ = IronMAgent._from_template(desk, {"template": "t1"}, None)
    assert ok == plan()


def test_turn_budget_stays_at_twenty() -> None:
    from ironm_agent.llm import load_models

    assert load_models().turn_budget == 20  # 12 会让排计划那一轮直接答不出来（审查 11-05）
