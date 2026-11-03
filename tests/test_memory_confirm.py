"""记忆结构第 4 步：定期确认（spec [2026-10-23] §154）。不连数据库、不调用模型。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from ironm_agent.memory_extract import changes_of, validate
from ironm_agent.memory_layers import AUTO, daily_asks, layers
from ironm_agent.memory_store import Change, MemoryBook
from tests.test_memory_layers import TODAY, at, item

GUESS = item(
    "g", "injury", "左膝半月板损伤", TODAY - timedelta(days=1), status="pending", origin="inferred"
)


def test_confirm_turns_a_guess_into_what_he_said() -> None:
    [op], bad = validate({"ops": [{"op": "confirm", "target": "m1", "quote": "对，就是半月板"}]},
                         {"m1": GUESS}, "对，就是半月板", "", today=TODAY)  # fmt: skip
    assert not bad and op.op == "confirm" and op.target is GUESS
    book = MemoryBook()
    asyncio.run(book.apply("42", [Change("insert", item=GUESS)]))
    asyncio.run(book.apply("42", changes_of([op])))
    [x] = asyncio.run(book.items("42"))  # 推测的那条被取代，新的一条是他说的、原话是他这句
    assert (x.status, x.origin, x.evidence, x.supersedes) == (
        "active",
        "said",
        "对，就是半月板",
        "g",
    )
    assert x.content == GUESS.content and x.key == "injury:joint.knee:左"  # 字段照旧（读时补上）


def test_still_the_same_moves_the_date_to_today() -> None:
    gear = item("a", "equipment", "家里有一对哑铃", TODAY - timedelta(days=100))
    [op], _ = validate({"ops": [{"op": "confirm", "target": "m1", "quote": "还是那对哑铃"}]},
                       {"m1": gear}, "对，还是那对哑铃", "", today=TODAY)  # fmt: skip
    assert changes_of([op]) == [Change("status", id="a", status="active")]
    book = MemoryBook()
    asyncio.run(book.apply("42", [Change("insert", item=gear)]))
    asyncio.run(book.apply("42", changes_of([op])))
    [x] = asyncio.run(book.items("42"))
    assert abs((datetime.now(UTC) - x.updated).total_seconds()) < 60 and x.origin == "said"


def test_confirm_needs_his_words_and_a_live_profile_item() -> None:
    known = {
        "m1": GUESS,
        "m2": item("e", "event", "这周出差"),
        "m3": replace(GUESS, status="superseded"),
    }
    for target, said, why in (
        ("m1", "嗯嗯", "原话片段在原文里找不到"),
        ("m1", "对", "原话片段在原文里找不到"),  # 一个字不够
        ("m2", "对", "确认的目标不存在，或不是还在用的画像记忆"),
        ("m3", "对", "确认的目标不存在，或不是还在用的画像记忆"),
        ("m9", "对", "确认的目标不存在，或不是还在用的画像记忆"),
    ):
        ops, bad = validate({"ops": [{"op": "confirm", "target": target, "quote": "对"}]}, known, said, "",
                            today=TODAY)  # fmt: skip
        assert ops == [] and bad == [why], target


def test_a_wrong_guess_is_dropped_not_marked_healed() -> None:
    [op], _ = validate({"ops": [{"op": "resolve", "target": "m1", "quote": "不是半月板"}]},
                       {"m1": GUESS}, "不是半月板，就是有点酸", "", today=TODAY)  # fmt: skip
    assert changes_of([op]) == [Change("status", id="g", status="superseded")]


def test_a_guess_is_asked_about_for_three_days_then_dropped() -> None:
    fresh = layers([GUESS], TODAY)
    assert "左膝半月板损伤？" in fresh.profile[0]
    assert fresh.asks == [
        "m1｜推测他「左膝半月板损伤」，还没确认：合适时问一句对不对（对就 confirm m1，不对就 resolve m1）"
    ]
    old = layers([replace(GUESS, created=at(TODAY - timedelta(days=4)))], TODAY)
    assert old.profile == [] and old.asks == []


def stale(i: str, cat: str, days: int, **kw: object) -> object:
    return item(i, cat, f"{cat} 的说法 {i}", TODAY - timedelta(days=days), **kw)  # type: ignore[arg-type]


def test_long_kept_facts_get_one_question_a_day() -> None:
    gear, rest = stale("a", "equipment", 90), stale("b", "schedule", 120)
    [ask] = [c.item for c in daily_asks([gear, rest], [], None, [], TODAY) if c.item]
    assert ask.evidence == AUTO + "stale:b" and "三个月没确认" in ask.content  # 最久的先问
    assert [c.item.evidence for c in daily_asks([gear], [], None, [], TODAY) if c.item] == [
        AUTO + "stale:a"
    ]
    assert ask.until == TODAY and ask.category == "followup"
    assert daily_asks([stale("a", "equipment", 89)], [], None, [], TODAY) == []
    hurt = [c.item for c in daily_asks([stale("i", "injury", 60)], [], None, [], TODAY) if c.item]
    assert "好久没提了" in hurt[0].content and "resolve" in hurt[0].content
    assert daily_asks([stale("i", "injury", 59)], [], None, [], TODAY) == []
    assert daily_asks([stale("p", "preference", 400)], [], None, [], TODAY) == []  # 喜好不问
    assert (
        daily_asks([stale("d", "level", 200, origin="data")], [], None, [], TODAY) == []
    )  # 训练记录推的不问


def test_the_same_fact_is_not_asked_again_within_a_month() -> None:
    gear = stale("a", "equipment", 100)
    [first] = [c.item for c in daily_asks([gear], [], None, [], TODAY) if c.item]
    first = replace(first, created=at(TODAY), updated=at(TODAY))
    assert daily_asks([gear, first], [], None, [], TODAY + timedelta(days=29)) == []
    again = daily_asks([gear, first], [], None, [], TODAY + timedelta(days=31))
    assert [c.item.evidence for c in again if c.item] == [AUTO + "stale:a"]


def test_the_question_points_at_the_fact_and_goes_once_confirmed() -> None:
    gear = stale("a", "equipment", 100)
    [ask] = [c.item for c in daily_asks([gear], [], None, [], TODAY) if c.item]
    lay = layers([gear, ask], TODAY)
    [line] = lay.asks
    assert line.endswith("（是 m1 那条）") and lay.handles["m1"] is gear
    assert lay.profile[0].endswith("很久没确认：用到它时答完问一句还是不是这样）")  # 画像那行也标出来
    assert "很久没确认" not in layers([stale("n", "equipment", 89)], TODAY).profile[0]
    later = replace(ask, created=at(TODAY))
    confirmed = replace(gear, updated=at(TODAY) + timedelta(hours=1))
    assert layers([confirmed, later], TODAY).asks == []
    assert layers([replace(gear, status="superseded"), later], TODAY).asks == []


def test_not_right_is_not_a_confirmation() -> None:
    ops, bad = validate({"ops": [{"op": "confirm", "target": "m1", "quote": "对的"}]}, {"m1": GUESS},
                        "不对的，不是半月板", "", today=TODAY)  # fmt: skip
    assert ops == [] and bad == ["他说的是不对"]


def test_saying_it_again_then_adding_more_keeps_the_update() -> None:
    """原样又说一遍、接着补了最重 15 公斤：补的不被"改了两次"挡掉（复核 11-03）。"""
    bells = item("b", "equipment", "家里有一对哑铃")
    again = {
        "op": "add",
        "category": "equipment",
        "content": "家里有一对哑铃",
        "quote": "家里有一对哑铃",
    }
    more = {
        "op": "update",
        "target": "m1",
        "content": "家里有一对哑铃，最重 15 公斤",
        "quote": "最重的是15公斤",
    }
    ops, bad = validate(
        {"ops": [again, more]}, {"m1": bells}, "我家里有一对哑铃，最重的是15公斤", "", today=TODAY
    )
    assert not bad and [o.op for o in ops] == ["update"]
    yes = {"op": "confirm", "target": "m1", "quote": "家里有一对哑铃"}
    ops, bad = validate(
        {"ops": [yes, more]}, {"m1": bells}, "我家里有一对哑铃，最重的是15公斤", "", today=TODAY
    )
    assert not bad and [o.op for o in ops] == ["update"]
    twice = {"op": "confirm", "target": "m1", "quote": "家里有一对哑铃"}
    ops, _ = validate({"ops": [twice, twice]}, {"m1": bells}, "我家里有一对哑铃", "", today=TODAY)
    assert [o.op for o in ops] == ["confirm"]


def test_a_dismissed_guess_event_still_ends_the_usual_way() -> None:
    sick = item("e", "event", "可能感冒了", status="pending", origin="inferred")
    [op], _ = validate({"ops": [{"op": "resolve", "target": "m1", "quote": "感冒好了"}]}, {"m1": sick},
                       "感冒好了", "", today=TODAY)  # fmt: skip
    assert [c.kind for c in changes_of([op])] == ["status", "insert"]  # 近况照旧：记一条已结束


def test_a_system_question_does_not_hide_a_cold() -> None:
    """长期没提的伤病生成了该问的：不顶掉正在生效的近况（复核 11-03）。"""
    hurt = item("i", "injury", "右肩撞击，推举时会疼", TODAY - timedelta(days=70))
    cold = item(
        "c", "event", "感冒了，这周不练", TODAY - timedelta(days=1), until=TODAY + timedelta(days=3)
    )
    [ask] = [c.item for c in daily_asks([hurt, cold], [], None, [], TODAY) if c.item]
    ask = replace(ask, created=at(TODAY), updated=at(TODAY))
    lay = layers([hurt, cold, ask], TODAY)
    assert any("感冒了" in e for e in lay.episodes) and any("右肩撞击" in a for a in lay.asks)


def test_a_guess_does_not_hide_what_he_said() -> None:
    """他说过左膝疼，之后推测成半月板损伤（同一处）：他说的那条照样带，推测的过期后也还在（复核 11-03）。"""
    said = replace(item("s", "injury", "左膝疼", TODAY - timedelta(days=6)), key="injury:joint.knee:左",
                   data={"parts": ["joint.knee"], "side": "左"})  # fmt: skip
    guess = replace(GUESS, key="injury:joint.knee:左", data={"parts": ["joint.knee"], "side": "左"})
    now_ = layers([said, guess], TODAY).profile
    assert len(now_) == 2 and any("左膝疼（" in x for x in now_) and any("？" in x for x in now_)
    later = layers([said, replace(guess, created=at(TODAY - timedelta(days=4)))], TODAY).profile
    assert len(later) == 1 and "左膝疼（" in later[0]
    assert daily_asks(
        [replace(said, updated=at(TODAY - timedelta(days=60))), guess], [], None, [], TODAY
    )


def test_reminders_he_asked_for_come_before_guesses() -> None:
    guesses = [
        item(f"g{i}", "diet", f"可能乳糖不耐受{i}", status="pending", origin="inferred")
        for i in range(3)
    ]
    due = item("f", "followup", "提醒他今天去复查膝盖", until=TODAY)
    asks = layers([*guesses, due], TODAY).asks
    assert len(asks) == 3 and "复查膝盖" in asks[0]


def test_one_question_a_day_even_after_a_restart() -> None:
    a, b = stale("a", "equipment", 120), stale("b", "schedule", 100)
    [first] = [c.item for c in daily_asks([a, b], [], None, [], TODAY) if c.item]
    first = replace(first, created=at(TODAY), updated=at(TODAY))
    assert daily_asks([a, b, first], [], None, [], TODAY) == []  # 同一天再查：今天已经问过一条
    [nxt] = [
        c.item for c in daily_asks([a, b, first], [], None, [], TODAY + timedelta(days=1)) if c.item
    ]
    assert nxt.evidence == AUTO + "stale:b"


def test_confirming_a_guess_keeps_what_he_said_about_the_same_knee() -> None:
    """他说过"左膝疼，深蹲会疼，不做深蹲"（带字段），推测成半月板损伤后他说对了：字段和他的话都留着（复核 11-03）。"""
    from ironm_agent.latest import current

    knee = {"parts": ["joint.knee"], "side": "左"}
    said = replace(item("s", "injury", "左膝疼，深蹲会疼", TODAY - timedelta(days=5)), key="injury:joint.knee:左",
                   data={**knee, "triggers": ["深蹲"], "avoid": ["深蹲"], "severity": "中"})  # fmt: skip
    guess = replace(GUESS, key="injury:joint.knee:左", data=dict(knee))
    [op], bad = validate({"ops": [{"op": "confirm", "target": "m2", "quote": "就是半月板"}]},
                         {"m1": said, "m2": guess}, "对，就是半月板", "", today=TODAY)  # fmt: skip
    assert not bad and op.content == "左膝半月板损伤，左膝疼，深蹲会疼"
    assert op.data["avoid"] == ["深蹲"] and op.data["severity"] == "中" and op.data["side"] == "左"
    book = MemoryBook()
    asyncio.run(book.apply("42", [Change("insert", item=said), Change("insert", item=guess)]))
    asyncio.run(book.apply("42", changes_of([op])))
    [now_] = current(asyncio.run(book.items("42")))  # 读的时候只剩合起来的这一条
    assert now_.data["avoid"] == ["深蹲"] and "深蹲会疼" in now_.content


def test_punctuation_differences_still_confirm() -> None:
    for said, quote in (("对,就是半月板", "对，就是半月板"), ("对 就是半月板", "对就是半月板")):
        ops, bad = validate({"ops": [{"op": "confirm", "target": "m1", "quote": quote}]}, {"m1": GUESS},
                            said, "", today=TODAY)  # fmt: skip
        assert not bad and [o.op for o in ops] == ["confirm"], said


def test_confirms_go_last_when_there_are_too_many() -> None:
    from ironm_agent.memory_extract import MAX_OPS

    bells = item("b", "equipment", "家里有一对哑铃")
    again = {
        "op": "add",
        "category": "equipment",
        "content": "家里有一对哑铃",
        "quote": "家里有一对哑铃",
    }
    likes = [{"op": "add", "category": "preference", "content": f"喜欢动作{i}", "quote": f"喜欢动作{i}"}
             for i in range(MAX_OPS)]  # fmt: skip
    text = "家里有一对哑铃，" + "，".join(f"喜欢动作{i}" for i in range(MAX_OPS))
    ops, _ = validate({"ops": [again, *likes]}, {"m1": bells}, text, "", today=TODAY)
    assert len(ops) == MAX_OPS and all(o.op == "add" for o in ops)


def test_a_confirmed_guess_is_not_a_new_illness() -> None:
    """后台提取：推测的说对了换成的那条标出来，不再当新说的事看一次生病（复核 11-03）。"""
    from ironm_agent.memory_extract import extract
    from tests.fakes import FakeLLM, jsonr

    reply = jsonr({"ops": [{"op": "confirm", "target": "m1", "quote": "就是半月板"}]})
    out = asyncio.run(extract(FakeLLM(lambda *_: reply), [GUESS], "对，就是半月板", "好的。"))
    [new] = [c.item for c in out.changes if c.item is not None]
    assert out.confirmed == {new.id}
