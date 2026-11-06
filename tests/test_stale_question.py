"""很久没确认的记忆（spec [2026-10-23] §182，取代 §160）：代码不再在回答后补"顺便问一下"，只把事实（哪条、上次确认的日期）
交给管家，问不问由管家定。不连数据库、不调用真实模型。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from ironm_agent.memory_store import Change
from tests.fakes import jsonr
from tests.test_memory_layers import TODAY, item

GEAR = replace(item("e", "equipment", "家里有一对 10 公斤哑铃和弹力带", TODAY - timedelta(days=100)),
               data={"place": "home", "gear": ["哑铃", "弹力带"]})  # fmt: skip
ASK = item("f", "followup", "「器械与场地：家里有一对 10 公斤哑铃和弹力带」三个月没确认了", until=TODAY,
           evidence="auto:stale:e", origin="system")  # fmt: skip  # 以前代码生成的


def _turn(monkeypatch: Any, said: str, answer: str) -> tuple[str, Any, Any]:
    from tests.test_single_agent import single
    from tests.test_turn_flow import TODAY as DAY
    from tests.test_turn_flow import run, text_of

    a, spy = single(lambda *_: jsonr({"answer": answer}), monkeypatch, old=True)
    now = datetime.now(UTC)
    then = datetime(DAY.year, DAY.month, DAY.day, 4, tzinfo=UTC) - timedelta(
        days=100
    )  # 这一轮的"今天"前 100 天
    gear = replace(GEAR, created=then, updated=then)
    ask = replace(ASK, created=now, updated=now, until=DAY)  # 这一轮的"今天"是测试固定的那天
    asyncio.run(a._memory.apply("42", [Change("insert", item=x) for x in (gear, ask)]))
    blocks, _ = run(a, said)
    return text_of(blocks), a, spy


def test_no_question_is_appended_and_the_coach_sees_the_fact(monkeypatch: Any) -> None:
    got, a, spy = _turn(
        monkeypatch, "今晚在家练什么好", "今晚练全身：高脚杯深蹲用哑铃 3 组〔经验〕。"
    )
    assert "顺便问一下" not in got and not got.rstrip().endswith("现在还是这样吗？")
    seen = spy.system + spy.user
    assert "很久没确认的记忆" in seen and "家里有一对 10 公斤哑铃和弹力带" in seen
    assert "三个月没确认了" not in seen  # 以前代码生成的该问的不再带
    [ask] = [x for x in asyncio.run(a._memory.items("42", current_only=False)) if x.id == "f"]
    assert ask.status == "active"  # 旧数据不动，只是不再带


def test_nothing_is_appended_when_he_says_he_is_unwell(monkeypatch: Any) -> None:
    got, _, _ = _turn(
        monkeypatch, "今天膝盖有点疼，在家练什么", "今天先轻一点：哑铃划船 3 组〔经验〕。"
    )
    assert "顺便问一下" not in got
