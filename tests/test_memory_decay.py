"""记忆衰减（spec [2026-10-23] §157）：软的两个月后淡出，历史两个月后归档。不连数据库、不调用模型。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from typing import Any

from ironm_agent.memory_layers import layers, recall_tool
from ironm_agent.memory_store import Change, MemoryBook
from ironm_agent.memory_view import Recall, archived, expired
from tests.test_memory_layers import TODAY, at, item


def aged(i: str, cat: str, text: str, days: int, **kw: Any) -> Any:
    return item(i, cat, text, TODAY - timedelta(days=days), **kw)


def line(x: Any) -> str:
    [one] = layers([x], TODAY).profile or [""]
    return one


def test_soft_memories_fade_after_two_months_and_go_after_four() -> None:
    assert "两个月前" not in line(aged("p", "preference", "不喜欢跑步", 59))
    assert line(aged("p", "preference", "不喜欢跑步", 60)).endswith(
        "两个月前说的：用到时可以顺带问一句还是不是这样）"
    )
    assert "两个月前" in line(aged("s", "style", "回答要简短", 119))
    assert line(aged("p", "preference", "不喜欢跑步", 120)) == ""
    assert line(aged("g", "goal", "想练出腹肌", 130)) == ""
    assert "明年 5 月跑半马" in line(
        aged("h", "goal", "明年 5 月跑半马", 130)
    )  # 带日子的目标不淡（复核 11-04）


def test_what_matters_for_the_body_does_not_fade() -> None:
    for x in (aged("d", "diet", "乳糖不耐受", 300), aged("n", "diet", "花生过敏", 300),
              aged("i", "injury", "左膝旧伤", 300), aged("e", "equipment", "家里一对哑铃", 300)):  # fmt: skip
        got = line(x)
        assert got and "两个月前" not in got, x.content
    assert line(aged("h", "diet", "早饭不吃", 130)) == ""  # 普通饮食习惯会淡
    assert "两个月前" not in line(
        aged("r", "preference", "喜欢早上练", 70, origin="data")
    )  # 训练记录推的照旧 56 天那条规则


def test_saying_it_again_starts_the_clock_over() -> None:
    old = aged("p", "preference", "不喜欢跑步", 200)
    assert line(old) == "" and expired(old, at(TODAY))
    again = replace(old, updated=at(TODAY))
    assert "不喜欢跑步" in line(again) and not expired(again, at(TODAY))


def test_faded_ones_are_left_out_of_recall_too() -> None:
    old = aged("p", "preference", "不喜欢跑步", 130)
    assert Recall.of([old], at(TODAY)).items == ()


def test_history_is_archived_after_two_months() -> None:
    cases = [
        (aged("a", "equipment", "家里一对哑铃", 61, status="superseded"), True),
        (aged("b", "equipment", "家里一对哑铃", 59, status="superseded"), False),
        (aged("c", "preference", "喜欢游泳", 61, status="resolved"), True),
        (aged("d", "injury", "右肩撞击", 300, status="resolved"), False),  # 旧伤还要记着
        (aged("e", "event", "出差", 90, until=TODAY - timedelta(days=61)), True),
        (aged("f", "event", "出差", 90, until=TODAY - timedelta(days=60)), False),
        (aged("g", "event", "感冒了", 68), True),  # 没写结束日：按 7 天算
        (aged("h", "event", "感冒了", 67), False),
        (aged("i", "followup", "问问膝盖", 68), True),
        (aged("j", "advice", "箱式深蹲", 61), True),
        (aged("k", "advice", "箱式深蹲", 59), False),
        (aged("l", "preference", "喜欢早上练", 61, origin="data"), True),
        (aged("m", "preference", "不喜欢跑步", 300), False),  # 有效的不归档（淡出是另一回事）
        (aged("n", "equipment", "家里一对哑铃", 300), False),
    ]
    for x, want in cases:
        assert archived(x, TODAY) is want, x.id


def test_archived_history_is_not_loaded_each_turn_but_recall_still_finds_it() -> None:
    book = MemoryBook()
    trip = aged("t", "event", "去上海出差", 100, until=TODAY - timedelta(days=90))
    knee = aged("k", "injury", "左膝旧伤", 100)
    asyncio.run(book.apply("42", [Change("insert", item=trip), Change("insert", item=knee)]))
    turn = asyncio.run(book.items("42", current_only=False, recent=TODAY))
    assert [x.id for x in turn] == ["k"]
    tool = recall_tool(turn, TODAY, load=lambda: book.items("42", current_only=False))
    assert "去上海出差" in asyncio.run(tool(None, {"query": "出差", "days": 365}))

    async def down() -> list[Any]:
        raise ConnectionError("db down")

    assert "没有查到" in asyncio.run(
        recall_tool(turn, TODAY, load=down)(None, {"query": "出差", "days": 365})
    )
