"""整轮里的记忆：作答前读进来交给管家，回答发出后在后台提取；暂停、失败都不影响回答。"""

import asyncio
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from ironm_agent.llm import ModelUnavailable, Reply, Stage
from ironm_agent.memory_store import Change, Item, MemoryBook
from tests.fakes import jsonr, system_of
from tests.test_plugin import agent, collect, text_of

T0 = datetime(2026, 10, 20, tzinfo=UTC)
KNOWN = [
    Item("k", "injury", "左膝有旧伤，深蹲蹲深了会疼", "左膝有旧伤", "said", "active", T0, T0),
    Item(
        "d", "equipment", "家里有一对哑铃，最重 20 公斤", "最重 20 公斤", "said", "active", T0, T0
    ),
    Item("m", "diet", "乳糖不耐受", "乳糖不耐受", "said", "active", T0, T0),
]
QUESTION = "今天在家练腿，怎么安排"
ANSWER = "用你最重 20 公斤的哑铃做高脚杯深蹲，深度控制在膝盖不疼的范围。"


class Script:
    """单 Agent 的假模型：作答环节记在 "agent" 下，提取记忆在 "memory" 下；选规程给不出合格结果。"""

    def __init__(self, ops: list[dict[str, Any]] | None = None, memory_down: bool = False) -> None:
        self.ops = ops or []
        self.memory_down = memory_down
        self.seen: dict[str, str] = {}
        self.calls: dict[str, int] = {}

    def __call__(self, stage: Stage, messages: Sequence[Mapping[str, Any]], tools: bool) -> Reply:
        system = system_of(messages)
        user = str(messages[1]["content"]) if len(messages) > 1 else ""
        key = "agent" if stage == "expert" else stage
        self.calls[key] = self.calls.get(key, 0) + 1
        self.seen[key] = system + "\n" + user
        if stage == "route":
            return Reply("不是 JSON")
        if key == "agent":
            return jsonr({"answer": ANSWER})
        if stage == "memory":
            if self.memory_down:
                raise ModelUnavailable("timeout")
            return jsonr({"ops": self.ops})
        return Reply(ANSWER)


def with_memory(items: list[Item]) -> MemoryBook:
    book = MemoryBook()
    asyncio.run(book.apply("42", [Change("insert", item=x) for x in items]))
    return book


def test_limits_in_memory_reach_the_agent_but_are_not_shown(monkeypatch: Any) -> None:
    """共享档案（spec [2026-10-23] §2）：伤病、器械、饮食等限制，作答时都看得到；前端不列出记忆。"""
    s = Script()
    blocks = collect(agent(s, monkeypatch=monkeypatch, memory=with_memory(KNOWN)), QUESTION)
    assert all(x in s.seen["agent"] for x in ("左膝有旧伤", "最重 20 公斤", "乳糖不耐受"))
    # 记忆不在前端显示：对话过程里既不列出记忆条目，也没有用了哪几类记忆的提示（回答本身照常用上记忆）
    shown = json.dumps(blocks, ensure_ascii=False)
    for hidden in (
        "记得你的情况",
        "参考你的记忆",
        "伤病与身体状况",
        "器械与场地",
        "饮食限制与习惯",
    ):
        assert hidden not in shown
    assert not any(x.content in shown for x in KNOWN)


def test_numbers_the_user_said_before_can_be_used_without_a_source(monkeypatch: Any) -> None:
    s = Script()
    blocks = collect(agent(s, monkeypatch=monkeypatch, memory=with_memory(KNOWN)), QUESTION)
    assert "最重 20 公斤的哑铃" in text_of(blocks)
    assert s.calls["agent"] == 1  # 一次通过核对，不用改
    s2 = Script()
    collect(agent(s2, monkeypatch=monkeypatch, memory=MemoryBook()), QUESTION)
    assert s2.calls["agent"] == 2  # 没有这条记忆时，20 公斤对不上出处，要改一次


def test_memory_is_extracted_after_the_answer(monkeypatch: Any) -> None:
    ops = [{"op": "add", "category": "event", "content": "今天在家练腿", "quote": "今天在家练腿"}]
    s = Script(ops)
    book = MemoryBook()
    blocks = collect(agent(s, monkeypatch=monkeypatch, memory=book), QUESTION)
    assert "最重 20 公斤" in text_of(blocks)
    assert f"用户：{QUESTION}" in s.seen["memory"] and "教练：用你最重" in s.seen["memory"]
    items = asyncio.run(book.items("42"))
    d = items[0].created.astimezone().date()  # "今天"存成日期（§103）
    assert [(x.category, x.content, x.origin) for x in items] == [
        ("event", f"{d.month}月{d.day}日在家练腿", "said")
    ]


def test_paused_memory_extracts_nothing_but_still_answers_with_it(monkeypatch: Any) -> None:
    book = with_memory(KNOWN)
    asyncio.run(book.set_paused("42", True))
    s = Script([{"op": "add", "category": "event", "content": "在家练腿", "quote": "在家练腿"}])
    collect(agent(s, monkeypatch=monkeypatch, memory=book), QUESTION)
    assert "memory" not in s.calls and "哑铃" in s.seen["agent"]
    assert len(asyncio.run(book.items("42"))) == len(KNOWN)


def test_extraction_failure_does_not_touch_the_answer(monkeypatch: Any) -> None:
    ok = collect(agent(Script(), monkeypatch=monkeypatch, memory=with_memory(KNOWN)), QUESTION)
    down = Script(memory_down=True)
    blocks = collect(agent(down, monkeypatch=monkeypatch, memory=with_memory(KNOWN)), QUESTION)
    assert down.calls["memory"] == 1
    assert text_of(blocks) == text_of(ok) and not any(b["type"] == "error" for b in blocks)


def test_broken_store_means_no_memory_not_no_answer(monkeypatch: Any) -> None:
    class Broken(MemoryBook):
        async def items(self, user_id: str, *, current_only: bool = True) -> list[Item]:
            raise ConnectionError("db down")

    blocks = collect(agent(Script(), monkeypatch=monkeypatch, memory=Broken()), QUESTION)
    assert text_of(blocks) and not any(b["type"] == "error" for b in blocks)


def test_emergency_turns_do_not_extract(monkeypatch: Any) -> None:
    s = Script([{"op": "add", "category": "injury", "content": "胸口痛", "quote": "胸口"}])
    book = MemoryBook()
    collect(agent(s, monkeypatch=monkeypatch, memory=book), "跑步的时候胸口突然很痛，现在还在疼")
    # 急症只调一次模型说话（§86），不提取记忆
    assert s.calls == {"agent": 1} and asyncio.run(book.items("42")) == []
