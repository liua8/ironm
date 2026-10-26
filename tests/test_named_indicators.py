"""问到自己的指标先查数据（spec [2026-10-23] §37）：认出指标名、规则预取、交给专业角色的话、
规程和路由。不连数据库、不调用真实模型。"""

from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from ironm_agent.indicators import named_indicators
from ironm_agent.llm import Reply, Stage
from ironm_agent.plugin import checked_note
from tests.fakes import FakeHealth, jsonr, route_reply, system_of
from tests.test_plugin import agent, collect


def test_recognises_indicator_names() -> None:
    assert named_indicators("我肌酐高嘛") == ["肌酐"]
    assert named_indicators("我的空腹血糖正常吗") == ["空腹血糖"]  # 不再单独算"血糖"
    assert named_indicators("体检报告 LDL 和总胆固醇偏高，alt 也高") == ["LDL", "总胆固醇", "ALT"]
    for text in ("深蹲怎么做", "今天练什么", "帮我排个计划", "TCL 电视"):
        assert named_indicators(text) == [], text


def test_checked_note_wording() -> None:
    none = checked_note(["肌酐"], "", 0, True)
    assert "没有找到肌酐的记录" in none and "第一句" in none and "不要当作已经偏高" in none
    some = checked_note(["空腹血糖"], "[r1] 空腹血糖 5.8 mmol/L", 1, True)
    assert "[r1]" in some and "参考范围" in some and "不算诊断" in some
    assert "没能读到" in checked_note(["肌酐"], "", 0, False)


class Seen:
    """记下专业角色收到的话；路由到康复恢复师。"""

    def __init__(self) -> None:
        self.expert_inputs: list[str] = []

    def __call__(
        self, stage: Stage, messages: Sequence[Mapping[str, Any]], has_tools: bool
    ) -> Reply:
        if stage == "route":
            return route_reply("pro", "recovery", [])
        if stage == "expert":
            self.expert_inputs.append("\n".join(str(m.get("content", "")) for m in messages))
            if "这一轮只请了你一位" in system_of(messages):
                return jsonr({"answer": "没有找到你的肌酐记录〔经验〕。"})
            return jsonr({"speak": True, "conclusion": "没有找到你的肌酐记录〔经验〕。"})
        return Reply("没有找到你的肌酐记录。")


def test_turn_checks_the_named_indicator_first(
    monkeypatch: pytest.MonkeyPatch, traces_in_memory: Any
) -> None:
    health = FakeHealth(rows=[])  # 健康记录里没有这项
    script = Seen()
    collect(agent(script, health=health, monkeypatch=monkeypatch), "我肌酐高嘛")
    first = next(a for a in health.asked if a.get("keywords"))
    assert first["keywords"] == ["肌酐"] and first["view"] == "latest"  # 作答前规则先查最新值
    assert any("没有找到肌酐的记录" in x for x in script.expert_inputs)
    trace = traces_in_memory.turns[-1]
    assert trace.trace["prefetch"] == {"asked": 1, "rows": 0, "ok": True}
    assert any(s["kind"] == "indicator_missing" for s in trace.signals)
    assert "肌酐" not in str(trace.trace["prefetch"])  # 运行记录不记指标名


def test_found_rows_can_be_cited(monkeypatch: pytest.MonkeyPatch, traces_in_memory: Any) -> None:
    script = Seen()
    collect(agent(script, health=FakeHealth(), monkeypatch=monkeypatch), "我的静息心率正常吗")
    assert any(
        "系统按问题先查了这个人的健康记录（静息心率）" in x and "[r" in x
        for x in script.expert_inputs
    )
    pre = traces_in_memory.turns[-1].trace["prefetch"]
    assert pre["asked"] == 1 and pre["rows"] > 0 and pre["ok"]


def test_no_named_indicator_no_prefetch(
    monkeypatch: pytest.MonkeyPatch, traces_in_memory: Any
) -> None:
    health = FakeHealth()
    collect(agent(Seen(), health=health, monkeypatch=monkeypatch), "膝盖疼还能练吗")
    assert not any(a.get("view") == "latest" and a.get("keywords") for a in health.asked)
    assert "prefetch" not in traces_in_memory.turns[-1].trace


def test_lab_questions_route_and_load_the_lab_skill() -> None:
    from ironm_agent.roles import Role
    from ironm_agent.router import keyword_route
    from ironm_agent.skills import pick

    assert keyword_route("我肌酐高嘛").primary is Role.RECOVERY
    assert "化验指标怎么看" in [x.name for x in pick(Role.RECOVERY, "我肌酐高嘛", frozenset())]
    assert "化验指标怎么看" in [x.name for x in pick(Role.NUTRITION, "我的血糖正常吗", frozenset())]
    assert "疼痛时怎么改动作" not in [
        x.name for x in pick(Role.RECOVERY, "我肌酐高嘛", frozenset())
    ]


def test_lab_and_metric_triggers_put_data_skills_first() -> None:
    """路由的模型选了伤痛类规程时，点到化验指标仍先装"化验指标怎么看"，点到日常指标先装"趋势解读"。"""
    from ironm_agent.indicators import kinds_of
    from ironm_agent.roles import Role
    from ironm_agent.skills import choose

    assert kinds_of(named_indicators("我肌酐高嘛")) == {"lab"}
    assert kinds_of(named_indicators("我最近心率和睡眠怎么样")) == {"metric"}
    got, _ = choose(
        Role.RECOVERY, "我肌酐高嘛", frozenset({"lab"}), None, ("rest-pain", "rest-return")
    )
    assert got[0].id == "data-labs"
    got, _ = choose(Role.RECOVERY, "我最近心率正常吗", frozenset({"metric"}), None, ())
    assert [x.id for x in got] == ["data-trend"]


def test_route_prompt_tells_the_model_to_pick_data_skills() -> None:
    from ironm_agent import routing

    assert "data-labs" in routing._PROMPT and "不要选伤痛" in routing._PROMPT


def test_echoed_data_sentence_is_merged() -> None:
    """同一件事写两遍（普通句子 + 带编号的标记）时合并成一句数据句，结论不丢、能通过核对。"""
    from ironm_agent.checks import check_text, merge_echoes, plain

    t = ("你的空腹血糖 5.1 mmol/L，参考范围 3.9–6.1，在范围内<statement>空腹血糖 5.1 mmol/L，参考范围 3.9–6.1"
         "<cite>[r3]</cite></statement>。")  # fmt: skip
    merged = merge_echoes(t)
    assert plain(merged) == "你的空腹血糖 5.1 mmol/L，参考范围 3.9–6.1，在范围内。"
    assert (
        check_text(merged, support={"r3": [5.1, 3.9, 6.1]}, entries={}, question="我的血糖正常吗")
        == []
    )
    empty = (
        "空腹血糖 5.1 mmol/L，参考范围 3.9–6.1<statement><cite>[r3]</cite></statement>，在范围内。"
    )
    assert (
        merge_echoes(empty)
        == "<statement>空腹血糖 5.1 mmol/L，参考范围 3.9–6.1<cite>[r3]</cite></statement>，在范围内。"
    )
    other = "昨晚睡了 6 小时<statement>你近 7 天平均睡 6.5 小时<cite>[r1]</cite></statement>。"
    assert merge_echoes(other) == other  # 数字不一样：不是重复，不合并


def test_trailing_zero_is_not_rounded_away() -> None:
    """ "6.0"是写到一位小数的数，不能拿 5.6 四舍五入成 6 来对上；写"6"时照旧允许。"""
    from ironm_agent.checks import check_text
    from ironm_agent.numbers import traced, written_numbers

    six = written_numbers("参考范围 4.0–6.0")[1]
    assert not traced(six, [5.3, 4.0, 5.6]) and traced(written_numbers("约 6")[0], [5.6])
    bad = "<statement>糖化血红蛋白 5.3%，参考范围 4.0–6.0<cite>[r2]</cite></statement>。"
    assert check_text(
        bad, support={"r2": [5.3, 4.0, 5.6]}, entries={}, question="血糖"
    )  # 编出来的上限拦得住


def test_remembered_injury_does_not_force_pain_skills_on_data_questions(
    monkeypatch: pytest.MonkeyPatch, traces_in_memory: Any
) -> None:
    """记忆里有膝伤：问肌酐不再强制装伤痛规程；问"膝盖疼还能练吗"照旧装。"""
    from ironm_agent.memory_store import Item, MemoryBook, now

    def memory() -> MemoryBook:
        book = MemoryBook()
        book._items["42"] = [Item(id="m1", category="injury", content="左膝半月板旧伤", evidence="左膝半月板伤过",
                                origin="said", status="active", created=now(), updated=now())]  # fmt: skip
        return book

    collect(
        agent(Seen(), health=FakeHealth(rows=[]), monkeypatch=monkeypatch, memory=memory()),
        "我肌酐高嘛",
    )
    assert traces_in_memory.turns[-1].trace["skills"]["recovery"] == ["data-labs"]
    collect(
        agent(Seen(), health=FakeHealth(rows=[]), monkeypatch=monkeypatch, memory=memory()),
        "帮我解读我的一些健康指标",
    )
    got = traces_in_memory.turns[-1].trace["skills"]["recovery"]  # 只说"指标"也算问数据（§39）
    assert "data-labs" in got and not {"rest-pain", "rest-return"} & set(got)
    collect(
        agent(Seen(), health=FakeHealth(rows=[]), monkeypatch=monkeypatch, memory=memory()),
        "我尿酸偏高严重吗",
    )
    got = traces_in_memory.turns[-1].trace["skills"]["recovery"]  # "尿酸"的"酸"不是酸痛（§39）
    assert "data-labs" in got and not {"rest-pain", "rest-return"} & set(got)
    collect(
        agent(Seen(), health=FakeHealth(rows=[]), monkeypatch=monkeypatch, memory=memory()),
        "膝盖疼还能练吗",
    )
    assert "rest-pain" in traces_in_memory.turns[-1].trace["skills"]["recovery"]
