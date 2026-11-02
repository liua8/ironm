"""作答时怎么用记忆：待确认、被取代、过期的不用；建议只带最近几条；增删改确认与暂停。"""

import asyncio
from datetime import UTC, datetime, timedelta

from ironm_agent.memory_store import Category, Change, Item, MemoryBook, Origin, Status
from ironm_agent.memory_view import Recall

NOW = datetime(2026, 10, 22, tzinfo=UTC)


def item(i: str, cat: Category, text: str, status: Status = "active", days: int = 1,
         supersedes: str | None = None) -> Item:  # fmt: skip
    at = NOW - timedelta(days=days)
    origin: Origin = "advice" if cat == "advice" else "said"
    return Item(i, cat, text, text, origin, status, at, at, supersedes)


ITEMS = [
    item("1", "injury", "左膝有旧伤，深蹲蹲深了会疼"),
    item("2", "equipment", "家里有一对哑铃，最重 20 公斤"),
    item("3", "diet", "乳糖不耐受"),
    item("4", "style", "回答简短"),
    item("5", "goal", "半年增肌 5 公斤"),
    item("6", "schedule", "是上班族", status="pending"),
    item("7", "injury", "腰去年扭过", status="resolved"),
    item("8", "equipment", "家里有一对哑铃", status="superseded"),
    item("9", "event", "上个月感冒了", days=30),
    item("10", "event", "昨天练完腿今天很酸", days=1),
    *[item(f"a{i}", "advice", f"建议{i}", days=10 - i) for i in range(7)],
]


def test_pending_superseded_and_expired_are_not_used() -> None:
    recall = Recall.of(ITEMS, NOW)
    used = [x.content for x in recall.items]
    assert "是上班族" not in used and "上个月感冒了" not in used
    assert "昨天练完腿今天很酸" in used
    resolved = next(x for x in recall.items if x.content == "腰去年扭过")
    assert resolved.status == "resolved"  # 已解决的伤病仍然带上
    assert sum("家里有一对哑铃" in x for x in used) == 1


def test_only_recent_advice_is_kept() -> None:
    shared = Recall.of(ITEMS, NOW).shared()
    assert "建议6" in shared and "建议2" in shared and "建议1" not in shared
    assert "回答简短" in shared  # 回答风格和建议一起交给管家


def test_numbers_text_lets_answers_use_what_the_user_said() -> None:
    recall = Recall.of(ITEMS, NOW)
    assert "20 公斤" in recall.numbers_text() and "建议" not in recall.numbers_text()
    assert Recall.of([], NOW).numbers_text() == "" and Recall().shared() == ""


def test_store_edit_confirm_delete_and_pause() -> None:
    book = MemoryBook()

    async def go() -> None:
        await book.apply("u", [Change("insert", item=x) for x in ITEMS])
        edited = await book.edit("u", "6", "工作日下班后练")
        assert edited is not None and edited.origin == "edited" and edited.status == "active"
        assert await book.confirm("u", "1") is None  # 不是待确认的
        assert await book.edit("u", "8", "x") is None  # 被取代的不能改
        # 删除会连同它取代过的旧版本一起删
        await book.apply("u", [Change("insert", item=item("11", "equipment", "哑铃最重 15 公斤",
                                                          supersedes="2"))])  # fmt: skip
        await book.apply("u", [Change("status", id="2", status="superseded")])
        assert await book.delete("u", "11")
        left = {x.id for x in await book.items("u", current_only=False)}
        assert "11" not in left and "2" not in left and "1" in left
        assert not await book.delete("u", "nope")
        assert not await book.paused("u")
        await book.set_paused("u", True)
        assert await book.paused("u")

    asyncio.run(go())
