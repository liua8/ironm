"""记忆结构第 4 步：定期确认（spec [2026-10-23] §154）。不连数据库、不调用模型。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from ironm_agent.memory_extract import changes_of, validate
from ironm_agent.memory_layers import AUTO, layers, unconfirmed_lines
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


def test_long_kept_facts_are_listed_with_their_date() -> None:
    """§182：很久没确认的不再由代码每天生成"该问的"，改成事实列给管家（带上次确认的日期），问不问由管家定。"""
    gear, rest = stale("a", "equipment", 90), stale("b", "schedule", 120)
    lines = unconfirmed_lines([gear, rest], TODAY)
    assert [x.split("：")[0] for x in lines] == ["可练时间与作息", "器械与场地"]  # 最久的在前
    assert "上次确认" in lines[0] and "120 天前" in lines[0]
    assert unconfirmed_lines([stale("a", "equipment", 89)], TODAY) == []
    assert unconfirmed_lines([stale("i", "injury", 60)], TODAY) != []
    assert unconfirmed_lines([stale("i", "injury", 59)], TODAY) == []
    assert unconfirmed_lines([stale("p", "preference", 400)], TODAY) == []  # 喜好不算
    assert unconfirmed_lines([stale("d", "level", 200, origin="data")], TODAY) == []  # 训练记录推的不算


def test_the_listed_fact_points_at_its_profile_line_and_goes_once_confirmed() -> None:
    gear = stale("a", "equipment", 100)
    lay = layers([gear], TODAY)
    assert lay.asks == [] and lay.stale == [f"m1｜器械与场地：equipment 的说法 a（{_md(TODAY - timedelta(days=100))}）"]
    assert lay.handles["m1"] is gear and lay.profile[0].endswith("很久没确认）")  # 画像那行只标事实
    assert "很久没确认" not in layers([stale("n", "equipment", 89)], TODAY).profile[0]
    confirmed = replace(gear, updated=at(TODAY) + timedelta(hours=1))
    assert layers([confirmed], TODAY).stale == []
    assert layers([replace(gear, status="superseded")], TODAY).stale == []


def test_old_generated_still_questions_are_not_shown() -> None:
    """以前代码生成的"还是这样吗"（auto:stale:）不再带；那条记忆照样列在很久没确认里。"""
    gear = stale("a", "equipment", 100)
    old_ask = item("q", "followup", "三个月没确认了：问一句", TODAY, until=TODAY, origin="system",
                   evidence=AUTO + "stale:a")  # fmt: skip
    lay = layers([gear, old_ask], TODAY)
    assert lay.asks == [] and len(lay.stale) == 1


def _md(d: object) -> str:
    return f"{d.month}月{d.day}日"  # type: ignore[attr-defined]


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


def test_a_long_unconfirmed_injury_does_not_hide_a_cold() -> None:
    """长期没提的伤病列在很久没确认里：不顶掉正在生效的近况（复核 11-03）。"""
    hurt = item("i", "injury", "右肩撞击，推举时会疼", TODAY - timedelta(days=70))
    cold = item(
        "c", "event", "感冒了，这周不练", TODAY - timedelta(days=1), until=TODAY + timedelta(days=3)
    )
    lay = layers([hurt, cold], TODAY)
    assert any("感冒了" in e for e in lay.episodes) and any("右肩撞击" in a for a in lay.stale)


def test_a_guess_does_not_hide_what_he_said() -> None:
    """他说过左膝疼，之后推测成半月板损伤（同一处）：他说的那条照样带，推测的过期后也还在（复核 11-03）。"""
    said = replace(item("s", "injury", "左膝疼", TODAY - timedelta(days=6)), key="injury:joint.knee:左",
                   data={"parts": ["joint.knee"], "side": "左"})  # fmt: skip
    guess = replace(GUESS, key="injury:joint.knee:左", data={"parts": ["joint.knee"], "side": "左"})
    now_ = layers([said, guess], TODAY).profile
    assert len(now_) == 2 and any("左膝疼（" in x for x in now_) and any("？" in x for x in now_)
    later = layers([said, replace(guess, created=at(TODAY - timedelta(days=4)))], TODAY).profile
    assert len(later) == 1 and "左膝疼（" in later[0]
    assert unconfirmed_lines([replace(said, updated=at(TODAY - timedelta(days=60))), guess], TODAY)


def test_reminders_he_asked_for_come_before_guesses() -> None:
    guesses = [
        item(f"g{i}", "diet", f"可能乳糖不耐受{i}", status="pending", origin="inferred")
        for i in range(3)
    ]
    due = item("f", "followup", "提醒他今天去复查膝盖", until=TODAY)
    asks = layers([*guesses, due], TODAY).asks
    assert len(asks) == 3 and "复查膝盖" in asks[0]
