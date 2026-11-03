"""记忆分清长期和短期（spec [2026-10-23] §103）：模型标长短，代码照着放；"今天"写成日期；同一轮同类事件只记一条。"""

from __future__ import annotations

from datetime import UTC, date, datetime

from ironm_agent import agent, memory_extract
from ironm_agent.memory_extract import validate
from ironm_agent.memory_layers import layers, search
from ironm_agent.memory_store import Item

TODAY = date(2026, 11, 2)


def op(category: str, content: str, quote: str, **kw: object) -> dict[str, object]:
    return {"op": "add", "category": category, "content": content, "quote": quote, **kw}


def one(raw: dict[str, object], said: str) -> memory_extract.Op:
    ops, rejected = validate({"ops": [raw]}, {}, said, "好的。", today=TODAY)
    assert len(ops) == 1, rejected
    return ops[0]


def test_short_things_go_to_recent_events_and_expire() -> None:
    meal = one(
        op("diet", "今天早餐只吃了一个苹果", "早上一个苹果", lasting="short"), "早上一个苹果"
    )
    assert meal.category == "event" and meal.until == TODAY
    assert meal.content == "11月2日早餐只吃了一个苹果"  # "今天"写成日期
    lift = one(op("level", "今天卧推60公斤做了5次", "今天卧推60公斤做了5次", lasting="short"),
               "今天卧推60公斤做了5次")  # fmt: skip
    assert lift.category == "event" and lift.until == TODAY
    trip = one(
        op("schedule", "这周出差", "这周出差", lasting="short", until="2026-11-08"), "这周出差"
    )
    assert trip.category == "event" and trip.until == date(2026, 11, 8)


def test_long_things_stay_in_the_profile() -> None:
    habit = one(op("diet", "乳糖不耐受", "我乳糖不耐受", lasting="long"), "我乳糖不耐受")
    assert habit.category == "diet" and habit.until is None
    old = one(op("diet", "每天早上喝一勺乳清", "每天早上喝一勺乳清"), "每天早上喝一勺乳清")
    assert old.category == "diet"  # 没标长短的照旧（旧模型、后台提取兜底）


def test_one_illness_said_twice_in_one_reply_is_kept_once() -> None:
    said = "今天在发烧，吃了布洛芬"
    ops, _ = validate({"ops": [op("event", "今天在发烧", "今天在发烧"),
                               op("event", "今天吃了布洛芬，仍在发烧", "吃了布洛芬")]},
                      {}, said, "好的。", today=TODAY)  # fmt: skip
    assert [o.content for o in ops] == ["11月2日在发烧"]


def test_old_items_are_shown_with_the_day_they_were_said() -> None:
    at = datetime(2026, 10, 27, 2, tzinfo=UTC)
    apple = Item("a", "diet", "今天早餐只吃了一个苹果", "早上一个苹果", "said", "active", at, at)
    sick = Item("b", "event", "从昨天起身体不舒服，今天还没好", "还没好", "said", "active", at, at,
                until=TODAY)  # fmt: skip
    text = layers([apple, sick], TODAY).text(TODAY)
    assert "10月27日早餐只吃了一个苹果" in text and "从10月26日起身体不舒服，10月27日还没好" in text
    assert "今天" not in text
    assert "10月27日早餐" in search([apple], "苹果", 30, TODAY)


def test_prompts_say_how_to_mark_and_what_not_to_keep() -> None:
    assert '"lasting":"long' in agent._PROMPT and "一顿饭、一次训练不记" in agent._PROMPT
    assert (
        "lasting：long" in memory_extract._PROMPT
        and "一次训练练了什么不记" in memory_extract._PROMPT
    )
    assert "在 memory 里用 update 改那一条" in agent._JUST_ASKED
