"""整轮里的记忆：作答前读进来分给各角色，回答发出后在后台提取；暂停、失败都不影响回答。"""

import asyncio
import json
import logging
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
    def __init__(self, ops: list[dict[str, Any]] | None = None, memory_down: bool = False) -> None:
        self.ops = ops or []
        self.memory_down = memory_down
        self.seen: dict[str, str] = {}
        self.calls: dict[str, int] = {}

    def __call__(self, stage: Stage, messages: Sequence[Mapping[str, Any]], tools: bool) -> Reply:
        system = system_of(messages)
        user = str(messages[1]["content"]) if len(messages) > 1 else ""
        key = stage if stage != "expert" else ("exercise" if "动作教练" in system else "nutrition")
        self.calls[key] = self.calls.get(key, 0) + 1
        self.seen[key] = system + "\n" + user
        if stage == "route":
            return jsonr({"intent": "pro", "primary": "exercise", "helpers": ["nutrition"]})
        if key == "exercise":
            return jsonr({"conclusion": ANSWER})
        if key == "nutrition":
            return jsonr({"conclusion": "练后吃点无乳糖的蛋白质〔经验〕"})
        if stage == "memory":
            if self.memory_down:
                raise ModelUnavailable("timeout")
            return jsonr({"ops": self.ops})
        return Reply(ANSWER + "练后吃点无乳糖的蛋白质〔经验〕。")


def with_memory(items: list[Item]) -> MemoryBook:
    book = MemoryBook()
    asyncio.run(book.apply("42", [Change("insert", item=x) for x in items]))
    return book


def test_each_expert_gets_its_part_of_the_memory(monkeypatch: Any, caplog: Any) -> None:
    caplog.set_level(logging.INFO, logger="ironm_agent.run")
    s = Script()
    blocks = collect(agent(s, monkeypatch=monkeypatch, memory=with_memory(KNOWN)), QUESTION)
    assert "左膝有旧伤" in s.seen["route"]  # 主教练调度时看画像
    assert "哑铃" in s.seen["exercise"] and "乳糖" not in s.seen["exercise"]
    assert "乳糖" in s.seen["nutrition"] and "哑铃" not in s.seen["nutrition"]
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
    # 各角色拿到哪几类只写进日志，只有类别、没有内容
    logged = [
        r.getMessage() for r in caplog.records if r.getMessage().startswith("ironm memory use")
    ]
    assert len(logged) == 1
    roles = json.loads(logged[0].removeprefix("ironm memory use "))["roles"]
    assert roles == {"exercise": ["injury", "equipment"], "nutrition": ["diet"]}
    assert "左膝" not in logged[0] and "乳糖" not in logged[0]


def test_numbers_the_user_said_before_can_be_used_without_a_source(monkeypatch: Any) -> None:
    s = Script()
    blocks = collect(agent(s, monkeypatch=monkeypatch, memory=with_memory(KNOWN)), QUESTION)
    assert "最重 20 公斤的哑铃" in text_of(blocks)
    assert s.calls["exercise"] == 1  # 一次通过核对，不用改
    s2 = Script()
    collect(agent(s2, monkeypatch=monkeypatch, memory=MemoryBook()), QUESTION)
    assert s2.calls["exercise"] == 2  # 没有这条记忆时，20 公斤对不上出处，要改一次


def test_memory_is_extracted_after_the_answer(monkeypatch: Any) -> None:
    ops = [{"op": "add", "category": "event", "content": "今天在家练腿", "quote": "今天在家练腿"}]
    s = Script(ops)
    book = MemoryBook()
    blocks = collect(agent(s, monkeypatch=monkeypatch, memory=book), QUESTION)
    assert "最重 20 公斤" in text_of(blocks)
    assert f"用户：{QUESTION}" in s.seen["memory"] and "教练：用你最重" in s.seen["memory"]
    items = asyncio.run(book.items("42"))
    assert [(x.category, x.content, x.origin) for x in items] == [("event", "今天在家练腿", "said")]


def test_paused_memory_extracts_nothing_but_still_answers_with_it(monkeypatch: Any) -> None:
    book = with_memory(KNOWN)
    asyncio.run(book.set_paused("42", True))
    s = Script([{"op": "add", "category": "event", "content": "在家练腿", "quote": "在家练腿"}])
    collect(agent(s, monkeypatch=monkeypatch, memory=book), QUESTION)
    assert "memory" not in s.calls and "哑铃" in s.seen["exercise"]
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
    assert s.calls == {} and asyncio.run(book.items("42")) == []
