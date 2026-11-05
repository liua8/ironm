"""很久没确认的那条：管家没问时代码补一句（spec [2026-10-23] §160）。不连数据库、不调用真实模型。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from ironm_agent.memory_layers import layers, stale_question
from ironm_agent.memory_store import Change
from tests.fakes import jsonr
from tests.test_memory_layers import TODAY, item

GEAR = replace(item("e", "equipment", "家里有一对 10 公斤哑铃和弹力带", TODAY - timedelta(days=100)),
               data={"place": "home", "gear": ["哑铃", "弹力带"]})  # fmt: skip
ASK = item("f", "followup", "「器械与场地：家里有一对 10 公斤哑铃和弹力带」三个月没确认了", until=TODAY,
           evidence="auto:stale:e", origin="system")  # fmt: skip
Q = "顺便问一下：你之前说「家里有一对 10 公斤哑铃和弹力带」，现在还是这样吗？"


def lay() -> Any:
    return layers([GEAR, ASK], TODAY)


def test_used_it_and_did_not_ask_gets_one_line() -> None:
    got, ask = stale_question(lay(), "今晚做高脚杯深蹲，用哑铃 3 组。")
    assert got == Q and ask is not None and ask.id == "f"
    assert stale_question(lay(), "每组 10 公斤就够。") == (
        "",
        None,
    )  # 只对上重量不算用到了（复核 11-04）


def test_no_line_when_already_asked_or_not_used() -> None:
    for answer in ("今晚用哑铃练。家里那对哑铃现在还是这样吧？", "今晚用哑铃练。你家那对哑铃还在吗？",
                   "今晚用哑铃练。器械有变化吗？", "今晚用哑铃练。哑铃是几公斤的？", "今晚去跑 5 公里。"):  # fmt: skip
        assert stale_question(lay(), answer) == ("", None), answer
    assert stale_question(lay(), "今晚用哑铃练。你现在还能跑吗？")[0] == Q  # 问的是别的，照样补
    assert stale_question(layers([GEAR], TODAY), "今晚用哑铃练。") == (
        "",
        None,
    )  # 没到期：不在该问的里


def test_a_question_the_coach_did_not_see_is_not_added() -> None:
    """该问的超过 3 条、这条被截掉了：管家没看到，代码也不补（复核 11-04）。"""
    early = [
        item(f"r{i}", "followup", f"提醒他复查{i}", until=TODAY - timedelta(days=1))
        for i in range(3)
    ]
    assert stale_question(layers([GEAR, ASK, *early], TODAY), "今晚用哑铃练。") == ("", None)


def test_schedule_needs_two_of_its_details() -> None:
    rest = replace(item("s", "schedule", "一周练 3 次，每次 45 分钟", TODAY - timedelta(days=100)),
                   data={"per_week": 3, "minutes": 45})  # fmt: skip
    ask = replace(ASK, id="g", evidence="auto:stale:s")
    lay2 = layers([rest, ask], TODAY)
    assert stale_question(lay2, "跑步 45 分钟就够了。") == ("", None)
    assert stale_question(lay2, "按一周 3 次、每次 45 分钟排。")[0].startswith("顺便问一下")


def test_guesses_and_injuries_are_left_to_the_coach() -> None:
    hurt = replace(
        item("i", "injury", "左膝疼，深蹲 60 公斤会疼", TODAY - timedelta(days=70)),
        data={"parts": ["joint.knee"]},
    )
    ask = replace(ASK, evidence="auto:stale:i")
    assert stale_question(layers([hurt, ask], TODAY), "深蹲先别上 60 公斤，左膝疼。") == ("", None)


def _turn(monkeypatch: Any, said: str, answer: str) -> tuple[str, Any]:
    from tests.test_single_agent import single
    from tests.test_turn_flow import TODAY as DAY
    from tests.test_turn_flow import run, text_of

    a, _ = single(lambda *_: jsonr({"answer": answer}), monkeypatch, old=True)
    now = datetime.now(UTC)
    gear = replace(GEAR, created=now - timedelta(days=100), updated=now - timedelta(days=100))
    ask = replace(ASK, created=now, updated=now, until=DAY)  # 这一轮的"今天"是测试固定的那天
    asyncio.run(a._memory.apply("42", [Change("insert", item=x) for x in (gear, ask)]))
    blocks, _ = run(a, said)
    return text_of(blocks), a


def test_the_line_is_added_once_and_the_question_is_closed(monkeypatch: Any) -> None:
    got, a = _turn(monkeypatch, "今晚在家练什么好", "今晚练全身：高脚杯深蹲用哑铃 3 组〔经验〕。")
    assert got.rstrip().endswith("现在还是这样吗？") and got.count("顺便问一下") == 1
    [ask] = [x for x in asyncio.run(a._memory.items("42", current_only=False)) if x.id == "f"]
    assert ask.status == "resolved"  # 补问过了：这条该问的结束，下一轮不再补（复核 11-04）


def test_not_when_he_says_he_is_unwell(monkeypatch: Any) -> None:
    got, _ = _turn(
        monkeypatch, "今天膝盖有点疼，在家练什么", "今天先轻一点：哑铃划船 3 组〔经验〕。"
    )
    assert "顺便问一下" not in got
