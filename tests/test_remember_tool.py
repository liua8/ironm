"""记忆改成工具（spec [2026-10-23] §145）：管家调 remember 记，回答 JSON 里不再有 memory。不调用真实模型。"""

from __future__ import annotations

from typing import Any

from ironm_agent.actions import ALWAYS, MAX_ACTIONS, RECORD_STATE, REMEMBER, Desk, Outcome
from ironm_agent.memory_store import Item
from tests.fakes import jsonr, remembering
from tests.test_memory_now import items, run
from tests.test_single_agent import single
from tests.test_turn_flow import run as run_without_memory

SQUAT = {"op": "add", "category": "injury", "content": "左膝疼，深蹲时更明显", "quote": "左膝疼"}


def test_remember_is_always_offered_and_does_not_use_up_actions() -> None:
    import asyncio

    async def ok(desk: Desk, args: Any) -> Outcome:
        return Outcome(True, "收到", kind="memory", what="memory")

    desk = Desk({REMEMBER: ok, "log_body": ok})
    desk.unlock(ALWAYS)
    assert REMEMBER in desk.unlocked
    for _ in range(MAX_ACTIONS + 3):  # 记忆和记今天的状态一样不计次
        assert asyncio.run(desk.run(REMEMBER, {})) == "收到"
    assert desk.calls == 0 and RECORD_STATE in ALWAYS


def test_written_after_the_answer_and_said_remembered_counts_as_done(monkeypatch: Any) -> None:
    a, s = single(remembering([SQUAT], {"answer": "记下了，深蹲先别蹲太深〔经验〕。"}), monkeypatch)
    blocks, seen = run(a, "我左膝疼，深蹲的时候更明显")
    [knee] = items(a)
    assert knee.category == "injury" and knee.status == "active" and seen["memory_now"] == 1
    assert "收到 1 条" in s.last
    assert "记下了" in str(blocks)  # 记了记忆："记下了"不算说了没做（§145）


def test_a_followup_quoting_the_coachs_own_promise_is_kept_until_the_answer(
    monkeypatch: Any,
) -> None:
    """跟进的原话可能出自管家自己的回答：调用时回答还没写，先收下；回答写完后核对通过就写入。"""
    promise = {"op": "add", "category": "followup", "content": "过两天问问膝盖怎么样",
               "quote": "过两天我问问你膝盖"}  # fmt: skip
    a, _ = single(
        remembering([promise], {"answer": "先休息，过两天我问问你膝盖〔经验〕。"}), monkeypatch
    )
    _, seen = run(a, "膝盖有点不舒服")
    [f] = items(a)
    assert f.category == "followup" and seen["memory_now"] == 1
    a, _ = single(remembering([promise], {"answer": "先休息〔经验〕。"}), monkeypatch)
    _, seen = run(a, "膝盖有点不舒服")
    assert items(a) == [] and seen["memory_now"] == 0  # 回答里也没有这句：照样不写


def test_not_offered_when_memory_is_off_for_this_question(monkeypatch: Any) -> None:
    a, s = single(remembering([SQUAT], {"answer": "好〔经验〕。"}), monkeypatch)
    _, seen = run_without_memory(a, "我左膝疼")  # 系统拼的问法（remember=False）
    assert items(a) == [] and "memory_now" not in seen
    assert "这一轮不记记忆" in s.last


def test_answer_json_memory_is_ignored_now(monkeypatch: Any) -> None:
    """回答 JSON 里再写 memory 不再生效：只有调用 remember 才算（一条路）。"""
    a, _ = single(lambda *_: jsonr({"answer": "好〔经验〕。", "memory": [SQUAT]}), monkeypatch)
    _, seen = run(a, "我左膝疼")
    assert items(a) == [] and "memory_now" not in seen


def test_an_unknown_number_is_sent_back_with_the_reason(monkeypatch: Any) -> None:
    import asyncio
    from datetime import UTC, datetime

    from ironm_agent.memory_store import Change, MemoryBook

    store = MemoryBook()
    t0 = datetime(2026, 10, 20, tzinfo=UTC)
    old = Item("e1", "equipment", "家里有一对哑铃", "家里有一对哑铃", "said", "active", t0, t0)
    asyncio.run(store.apply("42", [Change("insert", item=old)]))
    up = {
        "op": "update",
        "target": "m9",
        "content": "家里有一对哑铃，最重 15 公斤",
        "quote": "最重 15 公斤",
    }
    a, s = single(remembering([up], {"answer": "好〔经验〕。"}), monkeypatch)
    a._memory = store
    _, seen = run(a, "我家哑铃最重 15 公斤")
    assert "没记" in s.last and seen["memory_tool_rejected"] == 1  # 编号不存在：当场退回原因


def test_paused_memory_does_not_get_the_tool(monkeypatch: Any) -> None:
    """他暂停了记忆：不给 remember，回答里也就不会说记下了却没记（复核 11-03）。"""
    import asyncio

    a, s = single(remembering([SQUAT], {"answer": "好〔经验〕。"}), monkeypatch)
    asyncio.run(a._memory.set_paused("42", True))
    _, seen = run(a, "我左膝疼")
    assert items(a) == [] and "这一轮不记记忆" in s.last and "memory_now" not in seen


def test_resolving_a_followup_by_number_waits_for_the_answer(monkeypatch: Any) -> None:
    """按编号结束跟进时模型常不写类别：按那一条的类别认出是跟进，原话在回答里也能过（复核 11-03）。"""
    import asyncio
    from datetime import UTC, datetime

    from ironm_agent.memory_store import Change, MemoryBook

    store = MemoryBook()
    from tests.test_turn_flow import TODAY

    t0 = datetime.now(UTC)
    f = Item(
        "f1",
        "followup",
        "下周问问膝盖",
        "下周你再问问我膝盖",
        "said",
        "active",
        t0,
        t0,
        until=TODAY,
    )
    asyncio.run(store.apply("42", [Change("insert", item=f)]))
    done = {"op": "resolve", "target": "m1", "quote": "膝盖现在怎么样"}  # 没写类别
    a, s = single(
        remembering([done], {"answer": "上次说好问你：膝盖现在怎么样〔经验〕？"}), monkeypatch
    )
    a._memory = store
    _, seen = run(a, "还行")
    assert "收到 1 条" in s.last and seen["memory_now"] == 1
    left = [
        x
        for x in asyncio.run(store.items("42"))
        if x.category == "followup" and x.status == "active"
    ]
    assert not left  # 跟进结束了


def test_already_known_items_get_a_plain_answer(monkeypatch: Any) -> None:
    a, _ = single(remembering([SQUAT, SQUAT], {"answer": "好〔经验〕。"}), monkeypatch)
    run(a, "我左膝疼，深蹲的时候更明显")
    a2, s2 = single(remembering([SQUAT], {"answer": "好〔经验〕。"}), monkeypatch)
    a2._memory = a._memory
    run(a2, "我左膝疼，深蹲的时候更明显")
    assert "已经记着了" in s2.last


def test_said_recorded_counts_only_for_checked_lasting_memory() -> None:
    """说"记下了"：按回答核对通过的长期情况才算做了；一次训练被记成近况，顶替不了记训练（复核 11-03）。"""
    from ironm_agent.actions import Desk

    desk = Desk({})
    desk.memory = [
        {"op": "add", "category": "event", "content": "今天深蹲 5 组", "quote": "深蹲做了 5 组"}
    ]
    desk.memory_ok = lambda answer: False  # 只有近况：核对后不算
    assert desk.unmet("记下了，今天深蹲 5 组。")
    desk.memory_ok = lambda answer: True
    assert not desk.unmet("记下了你左膝的情况。")
    desk.memory_ok = None
    assert desk.unmet("记下了你左膝的情况。")


def test_memory_holds_ignores_events_and_checks_against_the_answer() -> None:
    from datetime import date

    from ironm_agent.plugin import _memory_holds

    knee = {"op": "add", "category": "injury", "content": "左膝疼", "quote": "左膝疼"}
    trip = {
        "op": "add",
        "category": "event",
        "content": "这周出差",
        "quote": "这周出差",
        "lasting": "short",
    }
    assert _memory_holds([knee], {}, "我左膝疼", "好", date(2026, 11, 3))
    assert not _memory_holds([trip], {}, "这周出差", "好", date(2026, 11, 3))
    assert not _memory_holds([knee], {}, "我右肩疼", "好", date(2026, 11, 3))  # 原话不在：不算


def test_at_most_eight_items_a_turn(monkeypatch: Any) -> None:
    parts = ["左膝", "右肩", "腰", "左脚踝", "右手腕", "颈椎", "左髋", "右肘", "上背"]
    many = [
        {"op": "add", "category": "injury", "content": f"{x}疼", "quote": f"{x}疼"} for x in parts
    ]
    a, s = single(remembering(many, {"answer": "好〔经验〕。"}), monkeypatch)
    run(a, "，".join(f"{x}疼" for x in parts))
    assert "收到 8 条" in s.last and len(items(a)) == 8  # 一轮最多 8 条（和后台提取一样）
