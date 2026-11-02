"""记忆改成四层（spec [2026-10-23] §73）：用户画像、情景记忆、该问的和待跟进、会话摘要。不连数据库、不调真模型。"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from ironm_agent.llm import Reply
from ironm_agent.memory_extract import changes_of, handles, validate
from ironm_agent.memory_layers import AUTO, daily_asks, layers, search
from ironm_agent.memory_store import Item, MemoryBook
from ironm_agent.session_summary import Summary, due, promises
from ironm_agent.training import Plan, WorkoutLog
from tests.fakes import jsonr
from tests.test_plan_ops import plan
from tests.test_single_agent import single
from tests.test_turn_flow import run

TODAY = date(2026, 10, 29)


def at(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 4, tzinfo=UTC)  # 北京时间中午


def item(i: str, cat: str, text: str, day: date = TODAY, status: str = "active",
         until: date | None = None, origin: str = "said", evidence: str = "x") -> Item:  # fmt: skip
    return Item(i, cat, text, evidence, origin, status, at(day), at(day), None, until)  # type: ignore[arg-type]


# ---- 用户画像 ------------------------------------------------------------------------------


def test_profile_lines_carry_date_and_source_and_mark_guesses() -> None:
    lay = layers([
        item("a", "equipment", "家里可调哑铃，最重 20 公斤", date(2026, 10, 22)),
        item("b", "injury", "左膝半月板旧伤", date(2026, 10, 23), status="pending"),
        item("c", "injury", "右肩撞击", date(2026, 9, 1), status="resolved"),
        item("d", "equipment", "家里一对哑铃", date(2026, 10, 1), status="superseded"),
        item("e", "goal", "减脂到 65 公斤", date(2026, 10, 26)),
    ], TODAY)  # fmt: skip
    text = "\n".join(lay.profile)
    assert "目标：减脂到 65 公斤（10月26日，你说的）" in text
    assert "伤病与身体状况：左膝半月板旧伤？（10月23日，推测的）" in text
    assert "伤病与身体状况（已好）：右肩撞击" in text
    assert "家里一对哑铃" not in text  # 被取代的不带
    assert lay.profile[0].startswith("m1｜目标")  # 目标排第一，带编号能更新


def test_agent_updates_a_profile_line_instead_of_adding() -> None:
    old = item("e1", "equipment", "家里有一对哑铃", date(2026, 10, 20))
    known = layers([old], TODAY).handles
    raw = {"ops": [{"op": "update", "target": "m1", "content": "家里一对哑铃，最重 15 公斤",
                    "quote": "最重的是 15 公斤"}]}  # fmt: skip
    ops, rejected = validate(raw, known, "我家哑铃最重的是 15 公斤", "", today=TODAY)
    changes = changes_of(ops)
    assert not rejected and changes[0].kind == "status" and changes[0].id == "e1"
    assert changes[1].item is not None and changes[1].item.supersedes == "e1"


# ---- 情景记忆 ------------------------------------------------------------------------------


def test_trip_said_three_times_stays_one_event() -> None:
    book = MemoryBook()

    def say(text: str, content: str, quote: str) -> None:
        items = asyncio.run(book.items("42"))
        raw = {"ops": [{"op": "add", "category": "event", "content": content, "quote": quote}]}
        ops, _ = validate(raw, handles(items), text, "", today=TODAY)
        asyncio.run(book.apply("42", changes_of(ops)))

    say("这周出差", "这周出差", "这周出差")
    say("出差延长到周日了", "出差到周日", "出差延长到周日")
    say("出差只有自重能练", "出差只能练自重", "出差只有自重")
    say("这几天感冒了", "感冒了", "感冒了")  # 另一种事：单独一条
    live = [x for x in asyncio.run(book.items("42")) if x.status == "active"]
    assert sorted(x.content for x in live) == ["出差只能练自重", "感冒了"]


def test_events_show_until_their_end_then_ask_then_drop() -> None:
    items = [
        item("a", "event", "出差", date(2026, 10, 25), until=date(2026, 10, 30)),
        item("b", "event", "感冒", date(2026, 10, 20), until=date(2026, 10, 28)),  # 昨天到期
        item("c", "event", "加班", date(2026, 10, 15), until=date(2026, 10, 24)),  # 5 天前到期
        item("d", "event", "没睡好", date(2026, 10, 24)),  # 没写到期日：7 天
        item("e", "event", "腿酸", date(2026, 10, 20)),  # 没写到期日，超过 7 天
    ]
    lay = layers(items, TODAY)
    shown = "\n".join(lay.episodes)
    assert "出差（10月25日说的，到10月30日）" in shown and "没睡好" in shown
    assert "感冒" not in shown and "腿酸" not in shown and "加班" not in shown
    assert len(lay.asks) == 2 and "「感冒」说到10月28日为止" in lay.asks[0]
    assert "腿酸" in lay.asks[1]  # 没写到期日的也到期一问（10-27 到期，2 天前）


def test_recall_finds_ended_and_superseded() -> None:
    items = [
        item("a", "event", "左膝下楼疼", date(2026, 9, 10), status="resolved"),
        item("b", "equipment", "家里一对哑铃", date(2026, 10, 1), status="superseded"),
        item("c", "event", "感冒", date(2026, 10, 28)),
    ]
    got = search(items, "膝", 90, TODAY)
    assert "9月10日｜近期事件：左膝下楼疼（已结束）" in got
    assert "哑铃（已被更新）" in search(items, "哑铃", 90, TODAY)
    assert search(items, "膝", 30, TODAY) == "没有查到。"


# ---- 该问的、待跟进 ---------------------------------------------------------------------------


def test_due_followups_shown_at_most_three_and_closed_ones_not() -> None:
    items = [
        item("a", "followup", "问问膝盖", until=date(2026, 10, 29)),
        item("b", "followup", "复测体重", until=date(2026, 10, 27)),
        item("c", "followup", "问睡眠", until=date(2026, 10, 28)),
        item("d", "followup", "问饮食", until=date(2026, 10, 26)),
        item("e", "followup", "还没到期", until=date(2026, 11, 3)),
        item("f", "followup", "提过了", until=date(2026, 10, 28), status="resolved"),
        item("g", "followup", "太久了", until=date(2026, 10, 20)),
    ]
    asks = layers(items, TODAY).asks
    assert len(asks) == 3 and all(x not in "".join(asks) for x in ("还没到期", "提过了", "太久了"))
    text = layers(items, TODAY).text(TODAY)
    assert "一次最多提一件" in text and "用编号标为已解决" in text


def test_followup_from_answer_gets_a_due_date() -> None:
    raw = {"ops": [{"op": "add", "category": "followup", "content": "问问左膝下楼还疼不疼",
                    "quote": "下周我再问问你膝盖", "until": "2026-11-02"}]}  # fmt: skip
    ops, rejected = validate(raw, {}, "好的", "先这样练，下周我再问问你膝盖。", today=TODAY)
    assert not rejected and ops[0].until == date(2026, 11, 2) and ops[0].category == "followup"
    raw2 = {
        "ops": [{"op": "add", "category": "followup", "content": "复测体重", "quote": "提醒我复测"}]
    }
    ops2, _ = validate(raw2, {}, "两周后提醒我复测", "", today=TODAY)
    assert ops2[0].until == TODAY + timedelta(days=7)  # 没写哪天：一周后


def test_daily_asks_for_recurring_pain_and_training_gap() -> None:
    pains = [("joint.knee", TODAY - timedelta(days=d)) for d in (1, 5, 9)]
    got = daily_asks([], pains, None, [], TODAY)
    assert len(got) == 1 and got[0].item is not None and "膝盖疼" in got[0].item.content
    assert got[0].item.evidence == AUTO + "pain:joint.knee" and got[0].item.origin == "system"
    known_injury = [item("i", "injury", "左膝旧伤，蹲深了疼")]
    assert daily_asks(known_injury, pains, None, [], TODAY) == []  # 画像里已有
    asked = [got[0].item]
    assert daily_asks(asked, pains, None, [], TODAY) == []  # 30 天内不重复
    assert daily_asks([], pains[:2], None, [], TODAY) == []  # 只有 2 天

    four = Plan.model_validate({**plan().model_dump(), "days_per_week": 4})
    monday = TODAY - timedelta(days=TODAY.weekday())
    logs = [WorkoutLog(day=monday - timedelta(days=7 * k + 2)) for k in range(3)]  # 每周 1 次
    gap = daily_asks([], [], four, logs, TODAY)
    assert (
        len(gap) == 1
        and gap[0].item is not None
        and "最近 3 周分别练了 1、1、1 次" in gap[0].item.content
    )
    enough = logs + [WorkoutLog(day=monday - timedelta(days=7 * k + 3)) for k in range(3)]
    assert daily_asks([], [], four, enough, TODAY) == []  # 每周 2 次，不到一半才问


# ---- 会话摘要 ------------------------------------------------------------------------------


def test_summary_due_after_three_then_every_four() -> None:
    old = Summary("s", "x", 3, at(TODAY))
    assert [due(None, n) for n in (2, 3)] == [False, True]
    assert [due(old, n) for n in (6, 7)] == [False, True]


def test_promises_need_a_quote_from_the_chat() -> None:
    lines = ["用户：膝盖还有点疼", "教练：先练箱式深蹲，下周我再问问你膝盖。"]
    raw = [{"content": "问问膝盖", "due": "2026-11-02", "quote": "下周我再问问你膝盖"},
           {"content": "编的", "due": "2026-11-02", "quote": "我没说过这句"}]  # fmt: skip
    got = promises(raw, lines, TODAY, [])
    assert [c.item.content for c in got if c.item] == ["问问膝盖"]
    assert promises(raw, lines, TODAY, [item("f", "followup", "问问膝盖")]) == []  # 已经有了


def test_summary_written_in_background_and_shown_in_the_next_session(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from ironm_agent import plugin

    a, _ = single(lambda *_: jsonr({"answer": "好〔经验〕"}), monkeypatch)

    class Writer:
        def __init__(self, *_: Any) -> None:
            self.calls: list[Any] = []

        async def chat(self, stage: str, messages: Any, **_: Any) -> Reply:
            assert stage == "memory"
            return jsonr({"summary": "定了先练箱式深蹲；左膝还疼。", "promises": [
                {"content": "问问左膝", "due": "2026-11-05", "quote": "下周再问问你膝盖"}]})  # fmt: skip

    monkeypatch.setattr(plugin, "TurnLLM", Writer)

    async def transcript(_: str) -> list[str]:
        return ["用户：膝盖疼", "教练：先练箱式深蹲，下周再问问你膝盖。", "用户：好", "用户：行"]

    a._transcript = transcript
    with caplog.at_level(logging.INFO):
        asyncio.run(a._summarize("42", "42:old", 2))  # 不到 3 句：不写
        assert asyncio.run(a._summaries.get("42", "42:old")) is None
        asyncio.run(a._summarize("42", "42:old", 3))
    got = asyncio.run(a._summaries.get("42", "42:old"))
    assert got is not None and got.text == "定了先练箱式深蹲；左膝还疼。" and got.turns == 3
    follow = [x for x in asyncio.run(a._memory.items("42")) if x.category == "followup"]
    assert [x.content for x in follow] == ["问问左膝"] and follow[0].until == date(2026, 11, 5)
    assert "箱式深蹲" not in caplog.text and "左膝" not in caplog.text  # 日志里没有内容

    b, s2 = single(lambda *_: jsonr({"answer": "接着上次的来〔经验〕"}), monkeypatch)
    b._summaries, b._memory = a._summaries, a._memory
    _, seen = run(b, "上次那个计划怎么样了", session="42:new")
    assert "之前的会话（摘要" in s2.user and "定了先练箱式深蹲" in s2.user
    assert seen["memory_layers"]["summaries"] == 1 and s2.stages == ["expert"]  # 作答时不多调模型


def test_the_agent_sees_layers_and_can_recall(monkeypatch: pytest.MonkeyPatch) -> None:
    from ironm_agent.memory_layers import RECALL
    from tests.fakes import call

    def answer(system: str, user: str, results: list[str]) -> Reply:
        if not results:
            return call(RECALL, query="膝", days=180)
        assert "左膝下楼疼（已结束）" in results[0]
        return jsonr({"answer": "你 9 月说过左膝下楼疼，后来好了〔经验〕。"})

    a, s = single(answer, monkeypatch)
    from ironm_agent.memory_store import Change

    asyncio.run(a._memory.apply("42", [Change("insert", item=item(
        "old", "event", "左膝下楼疼", date.today() - timedelta(days=50), status="resolved"))]))  # fmt: skip
    _, seen = run(a, "我以前膝盖是不是疼过")
    assert seen["tools"] == [RECALL] and "用户画像" in s.user and "情景记忆" in s.user
