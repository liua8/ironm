"""回答前先把上一轮的档案和记忆写完（spec [2026-10-23] §51）。不调用真实模型。"""

import asyncio
from datetime import date
from typing import Any

from ironm_agent.illness import Episode, IllnessBook
from ironm_agent.memory_store import MemoryBook
from tests.test_turn_flow import Coach, agent


def make(monkeypatch: Any) -> tuple[Any, list[dict[str, Any]]]:
    a = agent(Coach(), monkeypatch=monkeypatch, memory=MemoryBook())
    runs: list[dict[str, Any]] = []
    a._observe = runs.append
    return a, runs


async def ask(a: Any, text: str, user: str = "42") -> None:
    msgs = [{"role": "user", "content": text}]
    async for _ in a.generate_response(user, msgs, session_id=f"{user}:s1"):
        pass


def test_next_turn_reads_after_the_last_turn_is_written(monkeypatch: Any) -> None:
    a, runs = make(monkeypatch)
    order: list[str] = []
    read = a._recall

    async def slow_remember(*_: Any) -> None:
        await asyncio.sleep(0.2)
        order.append("written")

    async def spy_recall(user_id: str) -> Any:
        order.append("read")
        return await read(user_id)

    monkeypatch.setattr(a, "_remember", slow_remember)
    monkeypatch.setattr(a, "_recall", spy_recall)

    async def go() -> None:
        await ask(a, "我左膝有旧伤，深蹲要注意什么")  # 要提取记忆的一句
        await ask(a, "今天怎么练")  # 不等上一轮写完就问
        await a.settle()

    asyncio.run(go())
    assert order[:3] == ["read", "written", "read"]
    assert runs[-1]["sync_ms"] >= 150 and "sync_timeout" not in runs[-1]


def test_illness_ended_in_the_background_is_seen_by_the_next_turn(monkeypatch: Any) -> None:
    a, _ = make(monkeypatch)
    book = IllnessBook()
    a._illness = book
    today = date.today()
    ep = Episode(symptoms=["肚子疼"], level="below", started=today)
    seen: list[int] = []
    track = a._track_illness

    async def slow_remember(*_: Any) -> None:  # 后台提取记忆时记下"好了"
        await asyncio.sleep(0.2)
        await book.save("42", ep.model_copy(update={"status": "resolved", "ended": today}))

    async def spy_track(user_id: str, text: str, run: dict[str, Any]) -> Any:
        eps = await track(user_id, text, run)
        seen.append(sum(1 for x in eps if x.active))
        return eps

    monkeypatch.setattr(a, "_remember", slow_remember)
    monkeypatch.setattr(a, "_track_illness", spy_track)

    async def go() -> None:
        await book.save("42", ep)
        await ask(a, "我左膝有旧伤，深蹲要注意什么")
        await ask(a, "今天怎么练")
        await a.settle()

    asyncio.run(go())
    assert seen == [1, 0]


def test_other_peoples_pending_writes_are_not_waited_for(monkeypatch: Any) -> None:
    a, runs = make(monkeypatch)

    async def slow_remember(*_: Any) -> None:
        await asyncio.sleep(0.5)

    monkeypatch.setattr(a, "_remember", slow_remember)

    async def go() -> None:
        await ask(a, "我左膝有旧伤，深蹲要注意什么", user="42")
        await ask(a, "今天怎么练", user="43")
        await a.settle()

    asyncio.run(go())
    assert "sync_ms" not in runs[-1]


def test_waiting_has_a_limit(monkeypatch: Any) -> None:
    a, runs = make(monkeypatch)
    a._sync_wait = 0.1

    async def stuck_remember(*_: Any) -> None:
        await asyncio.sleep(0.6)

    monkeypatch.setattr(a, "_remember", stuck_remember)

    async def go() -> None:
        await ask(a, "我左膝有旧伤，深蹲要注意什么")
        await ask(a, "今天怎么练")
        await a.settle()

    asyncio.run(go())
    assert runs[-1]["sync_timeout"] >= 1 and 80 <= runs[-1]["sync_ms"] < 500
    assert runs[-1]["path"] != "error"


def test_no_wait_when_nothing_is_pending(monkeypatch: Any) -> None:
    a, runs = make(monkeypatch)
    asyncio.run(ask(a, "深蹲怎么做"))
    assert "sync_ms" not in runs[-1]
