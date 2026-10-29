"""记忆重做第 1 批（spec [2026-10-23] §68）：单 Agent 当场记、近况按到期日过期、后台兜底不靠关键词、
本会话列过的确认和预览说明给全文。"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any

from ironm_agent.clarify import HEAD
from ironm_agent.memory import COACH, thread_lines
from ironm_agent.memory_store import Change, Item, MemoryBook
from ironm_agent.memory_view import Recall
from tests.fakes import jsonr
from tests.test_plugin import text_of
from tests.test_single_agent import single
from tests.test_turn_flow import TODAY, shown
from tests.test_turn_flow import run as run_without_memory


def run(a: Any, text: str, session: str = "42:s1") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """当场写记忆的测试要打开写记忆（公共的 run 关着，相当于复盘等系统拼的问法）；后台提取不跑。"""
    seen: dict[str, Any] = {}
    a._observe, a._remember_on = seen.update, True
    a._later = lambda _u, work: work.close()

    async def go() -> list[dict[str, Any]]:
        msgs = [{"role": "user", "content": text}]
        return shown([b async for b in a.generate_response("42", msgs, session_id=session)])

    return asyncio.run(go()), seen


COLD = {"op": "add", "category": "event", "content": "感冒了，这周别练太狠", "quote": "我感冒了",
        "until": (TODAY + timedelta(days=30)).isoformat()}  # fmt: skip


def items(a: Any) -> list[Item]:
    return asyncio.run(a._memory.items("42", current_only=False))


def test_agent_writes_a_recent_event_on_the_spot_and_sees_it_next_turn(monkeypatch: Any) -> None:
    def answer(system: str, user: str, results: list[str]) -> Any:
        if "我感冒了" in user.split("\n", 1)[0]:
            return jsonr({"answer": "好，这几天先休息，好了再练〔经验〕。", "memory": [COLD]})
        return jsonr({"answer": "先别练，等感冒好了再说〔经验〕。"})

    a, s = single(answer, monkeypatch)
    sick: list[str] = []

    async def illness(_: str, changes: Any) -> None:  # 当场写的也交给生病记录（§46）
        sick.extend(c.item.content for c in changes if c.item is not None)

    a._illness_from_memory = illness
    blocks, seen = run(a, "我感冒了，这周别练太狠")
    assert sick == ["感冒了，这周别练太狠"]
    [cold] = items(a)
    assert cold.category == "event" and cold.until == TODAY + timedelta(days=30)
    assert cold.evidence == "我感冒了" and seen["memory_now"] == 1 and "休息" in text_of(blocks)
    run(a, "今天能练吗")
    assert "m1｜event 近期事件：感冒了，这周别练太狠" in s.user  # 下一轮带编号看得到
    assert '"memory"' in s.system and "until" in s.system


def test_unchecked_memory_is_not_written(monkeypatch: Any) -> None:
    bad = [
        {"op": "add", "category": "injury", "content": "左膝疼", "quote": "我膝盖疼了三年"},
        {"op": "add", "category": "equipment", "content": "哑铃 20 公斤", "quote": "家里有哑铃"},
    ]
    a, _ = single(lambda *_: jsonr({"answer": "知道了〔经验〕。", "memory": bad}), monkeypatch)
    _, seen = run(a, "家里有哑铃")
    assert items(a) == [] and seen["memory_now"] == 0 and seen["memory_now_rejected"] == 2


def test_agent_updates_an_existing_memory_by_its_number(monkeypatch: Any) -> None:
    store = MemoryBook()
    t0 = datetime(2026, 10, 20, tzinfo=UTC)
    old = Item("e1", "equipment", "家里有一对哑铃", "家里有一对哑铃", "said", "active", t0, t0)
    asyncio.run(store.apply("42", [Change("insert", item=old)]))
    up = {"op": "update", "target": "m1", "content": "家里有一对哑铃，最重 15 公斤",
          "quote": "最重的是 15 公斤"}  # fmt: skip
    a, _ = single(lambda *_: jsonr({"answer": "好，按 15 公斤来〔经验〕。", "memory": [up]}),
                  monkeypatch)  # fmt: skip
    a._memory = store
    run(a, "我家哑铃最重的是 15 公斤")
    rows = {x.id: x for x in items(a)}
    assert rows["e1"].status == "superseded"
    [new] = [x for x in rows.values() if x.id != "e1"]
    assert new.content == "家里有一对哑铃，最重 15 公斤" and new.supersedes == "e1"


def test_recent_events_expire_on_their_own_date_or_after_14_days() -> None:
    now = datetime(2026, 10, 28, 4, tzinfo=UTC)

    def event(i: str, days: int, until: date | None) -> Item:
        at = now - timedelta(days=days)
        return Item(i, "event", i, i, "said", "active", at, at, None, until)

    kept = Recall.of([
        event("出差到昨天", 2, date(2026, 10, 27)), event("出差到今天", 2, date(2026, 10, 28)),
        event("说了 20 天、写到下月", 20, date(2026, 11, 20)),
        event("没写日期、3 天前", 3, None), event("没写日期、15 天前", 15, None),
    ], now)  # fmt: skip
    assert {x.content for x in kept.items} == {
        "说了 20 天、写到下月",
        "出差到今天",
        "没写日期、3 天前",
    }


def _later_names(a: Any) -> list[str]:
    names: list[str] = []

    def later(_: str, work: Any) -> None:
        names.append(work.cr_code.co_name)
        work.close()

    a._later = later
    return names


def talk(a: Any, text: str) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    a._observe, a._remember_on = seen.update, True

    async def go() -> None:
        async for _ in a.generate_response("42", [{"role": "user", "content": text}],
                                           session_id="42:s1"):  # fmt: skip
            pass

    asyncio.run(go())
    return seen


def test_background_extraction_is_the_fallback_without_keyword_screening(monkeypatch: Any) -> None:
    a, _ = single(lambda *_: jsonr({"answer": "你好！〔经验〕"}), monkeypatch)
    names = _later_names(a)
    talk(a, "你好")  # 关键词判断会跳过的话：单 Agent 下照样后台提取
    assert "_remember" in names

    a, _ = single(lambda *_: jsonr({"answer": "好〔经验〕。", "memory": [COLD]}), monkeypatch)
    names = _later_names(a)
    seen = talk(a, "我感冒了")
    assert "_remember" not in names and seen["memory_extract"] == "agent"


def test_confirm_list_and_preview_note_stay_whole_in_the_session() -> None:
    ask = f"{HEAD}，我打算按这些排：\n" + "\n".join(
        f"{n}这一项写得很长很长" * 6 for n in "①②③④⑤"
    )  # fmt: skip
    rows = [{"role": "user", "content": "给我一份训练计划"}, {"role": "assistant", "content": ask}]
    for i in range(5):
        rows += [{"role": "user", "content": f"问题 {i}"},
                 {"role": "assistant", "content": f"回答 {i}\n第二段"}]  # fmt: skip
    plain = thread_lines(rows, "你为什么不问我器械")
    kept = thread_lines(rows, "你为什么不问我器械", keep=(HEAD,))
    assert not any("③" in x for x in plain)  # 原来：超过 4 条回答就看不到，开头也只留 150 字
    [line] = [x for x in kept if HEAD in x]
    assert line.startswith(COACH) and "③" in line and "⑤" in line


def test_system_written_questions_do_not_write_memory(monkeypatch: Any) -> None:
    # 每周复盘、首页提醒拼出来的问法（remember=False）：里面的话不是他说的，不当场记
    a, _ = single(lambda *_: jsonr({"answer": "好〔经验〕。", "memory": [COLD]}), monkeypatch)
    _, seen = run_without_memory(a, "我感冒了，这周别练太狠")
    assert items(a) == [] and "memory_now" not in seen


def test_guessed_injury_detail_waits_for_confirmation(monkeypatch: Any) -> None:
    guess = {
        "op": "add",
        "category": "injury",
        "content": "左膝半月板损伤",
        "quote": "膝盖最近有点响",
    }
    a, _ = single(
        lambda *_: jsonr({"answer": "先别深蹲到底〔经验〕。", "memory": [guess]}), monkeypatch
    )
    run(a, "我膝盖最近有点响")
    [knee] = items(a)
    assert knee.status == "pending"  # 左右、诊断原话里没有：推测的，先放着等他确认
    said = {"op": "add", "category": "injury", "content": "左膝疼", "quote": "左膝疼"}
    a, _ = single(
        lambda *_: jsonr({"answer": "先别深蹲到底〔经验〕。", "memory": [said]}), monkeypatch
    )
    run(a, "我左膝疼")
    assert items(a)[0].status == "active"
