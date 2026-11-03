"""记忆结构第 2 步：器械和可练时间结构化（spec [2026-10-23] §150）。不连数据库、不调用真实模型。"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from typing import Any

import pytest

from ironm_agent.exercises import EQUIPMENT
from ironm_agent.facts import derive_equipment, derive_schedule, equipment, key_of, structured
from ironm_agent.memory_extract import validate
from ironm_agent.memory_store import Change, Item, MemoryBook
from tests.fakes import remembering
from tests.test_memory_now import items, run
from tests.test_single_agent import single

TODAY = date(2026, 11, 3)
T0 = datetime(2026, 11, 3, tzinfo=UTC)


def gear(content: str, **kw: Any) -> Item:
    return Item(kw.pop("id", "g1"), "equipment", content, content, "said", "active", T0, T0, **kw)


def test_derive_equipment_and_schedule() -> None:
    assert derive_equipment("在家练，有一对 10 公斤哑铃和弹力带") == {
        "place": "home",
        "gear": ["哑铃", "弹力带"],
    }
    assert derive_equipment("在健身房练，器械都有") == {"place": "gym"}
    assert derive_equipment("健身房和家里都练；家里有壶铃") == {"place": "both", "gear": ["壶铃"]}
    assert derive_equipment("还买了壶铃") == {"gear": ["壶铃"]}
    assert derive_equipment("家里有划船机") == {"gear": ["器械"]}  # 补一样器械，不是说在哪练
    assert derive_schedule("每周能练 3 次，每次 40 分钟") == {"per_week": 3, "minutes": 40}
    assert derive_schedule("一周两次，周二和周六，每次一个半小时") == {
        "per_week": 2,
        "days": [2, 6],
        "minutes": 90,
    }
    assert derive_schedule("周末有空") == {}


def test_given_fields_must_be_what_he_said() -> None:
    ok = structured("equipment", {"place": "home", "gear": ["哑铃"], "custom": ["瑜伽垫"]},
                    "在家练，有哑铃和瑜伽垫", "在家练，有哑铃和瑜伽垫")  # fmt: skip
    assert ok == ("equipment", {"place": "home", "gear": ["哑铃"], "custom": ["瑜伽垫"]}, "")
    assert (
        structured("equipment", {"gear": ["杠铃"]}, "在家练，有哑铃", "在家练，有哑铃")[2]
        == "器械和原话对不上"
    )
    assert "场所" in structured("equipment", {"place": "gym"}, "在家练", "在家练")[2]
    assert "custom" in structured("equipment", {"gear": ["飞机"]}, "有哑铃", "有哑铃")[2]
    assert "自己加的" in structured("equipment", {"custom": ["TRX"]}, "有哑铃", "有哑铃")[2]
    s = structured("schedule", {"per_week": 3, "days": [1, 3, 5], "minutes": 40},
                   "每周 3 次，周一三五，每次 40 分钟", "每周 3 次，周一、周三、周五，每次 40 分钟")  # fmt: skip
    assert s == ("schedule", {"per_week": 3, "days": [1, 3, 5], "minutes": 40}, "")
    assert "每周几次" in structured("schedule", {"per_week": 5}, "每周 3 次", "每周 3 次")[2]
    assert "哪几天" in structured("schedule", {"days": [7]}, "周一有空", "周一有空")[2]
    assert "分钟" in structured("schedule", {"minutes": 90}, "每次 40 分钟", "每次 40 分钟")[2]


def test_only_full_statements_have_a_key() -> None:
    assert key_of("equipment", {"place": "home", "gear": ["哑铃"]}) == "equipment"
    assert key_of("equipment", {"gear": ["壶铃"]}) == ""  # 补一句：不带键，不顶掉原来的
    assert (
        key_of("schedule", {"per_week": 3}) == "schedule"
        and key_of("schedule", {"minutes": 40}) == ""
    )


def test_a_new_place_updates_and_an_addition_stays_separate() -> None:
    old = gear("在家练，有哑铃", data={"place": "home", "gear": ["哑铃"]}, key="equipment")
    moved = {
        "op": "add",
        "category": "equipment",
        "content": "现在在健身房练",
        "quote": "现在在健身房练",
    }
    [got], _ = validate({"ops": [moved]}, {"m1": old}, "我现在在健身房练", "", today=TODAY)
    assert got.op == "update" and got.target is old and got.data["place"] == "gym"
    more = {"op": "add", "category": "equipment", "content": "还买了壶铃", "quote": "还买了壶铃"}
    [add], _ = validate({"ops": [more]}, {"m1": old}, "我还买了壶铃", "", today=TODAY)
    assert add.op == "add" and add.target is None and add.key == ""


def test_equipment_reads_fields_and_old_sentences() -> None:
    assert equipment([]) is None
    assert equipment([gear("x", data={"place": "gym"})]) == frozenset(EQUIPMENT)
    home = gear("在家练，有哑铃", data={"place": "home", "gear": ["哑铃"]})
    kettle = gear("还买了壶铃", id="g2", data={"gear": ["壶铃"]})
    assert equipment([home, kettle]) == frozenset({"自重", "哑铃", "壶铃"})  # 补的一句合起来
    rower = gear("家里有划船机", data={"place": "home", "custom": ["划船机"]})
    assert equipment([rower]) == frozenset({"自重", "器械"})
    assert equipment([gear("家里有弹力带")]) == frozenset({"自重", "弹力带"})  # 没字段：照旧按句子
    assert equipment([gear("在健身房练")]) == frozenset(EQUIPMENT)
    assert equipment([home, Item("g3", "equipment", "x", "x", "said", "superseded", T0, T0,
                                 data={"gear": ["杠铃"]})]) == frozenset({"自重", "哑铃"})  # fmt: skip


def test_gear_page_stores_and_reads_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    from ironm_agent import web
    from tests.test_live import client as live_client

    c, _, _ = live_client(monkeypatch)
    memory = MemoryBook()
    c.app.dependency_overrides[web.memory_store] = lambda: memory  # type: ignore[attr-defined]
    r = c.put(
        "/iron/api/gear", json={"place": "home", "gear": ["哑铃"], "custom": ["划船机"]}
    ).json()
    assert r["place"] == "home" and r["gear"] == ["哑铃"] and r["custom"] == ["划船机"]
    [row] = asyncio.run(memory.items("42"))
    assert (
        row.data == {"place": "home", "gear": ["哑铃"], "custom": ["划船机"]}
        and row.key == "equipment"
    )
    assert equipment([row]) == frozenset({"自重", "哑铃", "器械"})
    gym = c.put("/iron/api/gear", json={"place": "gym", "gear": [], "custom": ["TRX"]}).json()
    assert gym["place"] == "gym" and gym["custom"] == []  # 健身房不留自己加的（同原来）


def test_tool_context_reads_items() -> None:
    from ironm_agent.protools.registry import ToolContext

    home = gear("在家练，有哑铃", data={"place": "home", "gear": ["哑铃"]})
    ctx = ToolContext.build(
        TODAY, goal=None, weight_kg=None, readings=None, injured=[], equipment_items=[home]
    )
    assert ctx.equipment == frozenset({"自重", "哑铃"})
    old = ToolContext.build(
        TODAY, goal=None, weight_kg=None, readings=None, injured=[], equipment_said=["家里有壶铃"]
    )
    assert old.equipment == frozenset({"自重", "壶铃"})


def test_remember_equipment_and_schedule(monkeypatch: Any) -> None:
    home = {"op": "add", "category": "equipment", "content": "在家练，有一对 10 公斤哑铃和弹力带",
            "quote": "在家练，有一对 10 公斤哑铃和弹力带", "place": "home", "gear": ["哑铃", "弹力带"]}  # fmt: skip
    a, _ = single(remembering([home], {"answer": "好〔经验〕。"}), monkeypatch)
    run(a, "我在家练，有一对 10 公斤哑铃和弹力带")
    more = {"op": "add", "category": "equipment", "content": "还买了壶铃", "quote": "还买了壶铃",
            "gear": ["壶铃"]}  # fmt: skip
    a2, _ = single(remembering([more], {"answer": "好〔经验〕。"}), monkeypatch)
    a2._memory = a._memory
    run(a2, "我还买了壶铃")
    assert equipment(items(a2)) == frozenset({"自重", "哑铃", "弹力带", "壶铃"})
    week = {"op": "add", "category": "schedule", "content": "每周能练 3 次，每次 40 分钟",
            "quote": "每周能练 3 次，每次 40 分钟", "per_week": 3, "minutes": 40}  # fmt: skip
    a3, _ = single(remembering([week], {"answer": "好〔经验〕。"}), monkeypatch)
    run(a3, "我每周能练 3 次，每次 40 分钟")
    [s] = items(a3)
    assert s.data == {"per_week": 3, "minutes": 40} and s.key == "schedule"
    wrong = {**home, "gear": ["杠铃"]}
    a4, s4 = single(remembering([wrong], {"answer": "好〔经验〕。"}), monkeypatch)
    run(a4, "我在家练，有一对 10 公斤哑铃和弹力带")
    assert items(a4) == [] and "器械和原话对不上" in s4.last


def test_old_equipment_rows_get_fields_when_read() -> None:
    store = MemoryBook()
    asyncio.run(store.apply("42", [Change("insert", item=gear("在家练，家里有哑铃、弹力带"))]))
    [row] = asyncio.run(store.items("42"))
    assert row.data == {"place": "home", "gear": ["哑铃", "弹力带"]} and row.key == "equipment"


def test_both_places_mean_everything() -> None:
    assert equipment(
        [gear("健身房和家里都练；家里有壶铃", data={"place": "both", "gear": ["壶铃"]})]
    ) == frozenset(EQUIPMENT)


def test_an_update_keeps_what_was_not_said_again() -> None:
    old = Item("s1", "schedule", "每周 3 次，每次 40 分钟", "每周 3 次，每次 40 分钟", "said", "active", T0, T0,
               data={"per_week": 3, "minutes": 40}, key="schedule")  # fmt: skip
    op = {"op": "update", "target": "m1", "category": "schedule", "content": "每次能练 60 分钟了",
          "quote": "每次能练 60 分钟了"}  # fmt: skip
    [got], _ = validate({"ops": [op]}, {"m1": old}, "我现在每次能练 60 分钟了", "", today=TODAY)
    assert got.data == {"per_week": 3, "minutes": 60} and got.key == "schedule"


def test_an_addition_with_home_in_it_does_not_replace_the_gym() -> None:
    """ "家里还有个壶铃"只是补一样器械：健身房那条照旧（复核 11-03）。"""
    gym = gear("在健身房练", data={"place": "gym"}, key="equipment")
    more = {
        "op": "add",
        "category": "equipment",
        "content": "家里还有个壶铃",
        "quote": "家里还有个壶铃",
    }
    [got], _ = validate({"ops": [more]}, {"m1": gym}, "家里还有个壶铃", "", today=TODAY)
    assert got.op == "add" and got.target is None and got.key == ""
    store = MemoryBook()  # 旧记录读的时候补字段：也不会互相顶掉
    asyncio.run(store.apply("42", [Change("insert", item=gear("在健身房练", id="a")),
                                   Change("insert", item=gear("家里还有个壶铃", id="b"))]))  # fmt: skip
    assert equipment(asyncio.run(store.items("42"))) == frozenset(EQUIPMENT)


def test_moving_place_does_not_keep_old_gear_but_an_addition_does() -> None:
    old = gear("在家练，有哑铃", data={"place": "home", "gear": ["哑铃"]}, key="equipment")
    moved = {"op": "update", "target": "m1", "category": "equipment", "content": "搬家了，在家练，只有自重",
             "quote": "搬家了，在家练，只有自重"}  # fmt: skip
    [got], _ = validate({"ops": [moved]}, {"m1": old}, "搬家了，在家练，只有自重", "", today=TODAY)
    assert got.data == {"place": "home"}
    more = {
        "op": "update",
        "target": "m1",
        "category": "equipment",
        "content": "还买了壶铃",
        "quote": "还买了壶铃",
    }
    [add], _ = validate({"ops": [more]}, {"m1": old}, "还买了壶铃", "", today=TODAY)
    assert add.data == {"place": "home", "gear": ["哑铃", "壶铃"]} and add.key == "equipment"


def test_schedule_rows_from_training_records_do_not_shadow_each_other() -> None:
    from ironm_agent.latest import current

    store = MemoryBook()
    rows = [Item("d1", "schedule", "通常在周一、周三练", "x", "data", "active", T0, T0),
            Item("d2", "schedule", "每周大约练 3 次", "x", "data", "active", T0, T0)]  # fmt: skip
    asyncio.run(store.apply("42", [Change("insert", item=x) for x in rows]))
    got = asyncio.run(store.items("42"))
    assert {x.key for x in got} == {""} and len(current(got)) == 2


def test_schedule_words() -> None:
    assert derive_schedule("每周三次") == {"per_week": 3} and derive_schedule("每周三练") == {
        "days": [3]
    }
    assert derive_schedule("周一三五") == {"days": [1, 3, 5]} and derive_schedule("两周一次") == {}
    assert derive_schedule("每周3-4次") == {"per_week": 3} and derive_schedule("每天") == {
        "per_week": 7
    }
    assert derive_schedule("每次1.5小时") == {"minutes": 90}


def test_a_new_place_shadows_an_old_one_without_fields() -> None:
    from ironm_agent.latest import current

    form = gear(
        "在家练，家里有哑铃", id="f", data={"place": "home", "gear": ["哑铃"]}, key="equipment"
    )
    trip = Item(
        "t", "equipment", "出差在酒店练", "出差在酒店练", "said", "active", T0.replace(day=4), T0
    )
    assert [x.id for x in current([form, trip])] == ["t"]


def test_tighter_checks() -> None:
    said = "每周 3 次，周一有空，每次 10 分钟"
    assert "哪几天" in structured("schedule", {"days": [True]}, said, said)[2]
    assert (
        "每周几次" in structured("schedule", {"per_week": 1}, said, said)[2]
    )  # "周一"不是每周 1 次
    got = structured(
        "equipment", {"custom": ["哑铃", "哑", "瑜伽垫"]}, "有哑铃和瑜伽垫", "有哑铃和瑜伽垫"
    )
    assert got[1].get("custom") == ["瑜伽垫"]


def test_gear_page_replaces_additions_too(monkeypatch: pytest.MonkeyPatch) -> None:
    from ironm_agent import web
    from tests.test_live import client as live_client

    c, _, _ = live_client(monkeypatch)
    memory = MemoryBook()
    asyncio.run(memory.apply("42", [Change("insert", item=gear("在家练，有哑铃", id="a")),
                                    Change("insert", item=gear("还买了壶铃", id="b"))]))  # fmt: skip
    c.app.dependency_overrides[web.memory_store] = lambda: memory  # type: ignore[attr-defined]
    c.put("/iron/api/gear", json={"place": "home", "gear": ["弹力带"]})
    assert equipment(asyncio.run(memory.items("42"))) == frozenset({"自重", "弹力带"})


def test_not_going_to_the_gym_and_the_latest_place_wins() -> None:
    assert derive_equipment("我不去健身房了，在家练") == {"place": "home"}
    gym = gear("在健身房练", id="g", data={"place": "gym"}, key="equipment")
    later = T0.replace(day=5)
    home = Item("h", "equipment", "在家练，只有弹力带", "在家练，只有弹力带", "said", "active", later, later,
                data={"place": "home", "gear": ["弹力带"]}, key="equipment")  # fmt: skip
    assert equipment([gym, home]) == frozenset({"自重", "弹力带"})  # 最近的为准，不再是器械都有


def test_second_review_fixes() -> None:
    """复核 11-03：管家交的场所要是他说了在哪练；"每周五天"不是周五周日；推测的不挤掉生效的；几种说法。"""
    assert (
        "场所" in structured("equipment", {"place": "home"}, "家里还有个壶铃", "家里还有个壶铃")[2]
    )
    assert (
        "场所"
        in structured(
            "equipment", {"place": "gym"}, "健身房太远不去了，在家练", "健身房太远不去了，在家练"
        )[2]
    )
    assert derive_schedule("每周五天") == {"per_week": 5} and derive_schedule("周一到周五") == {
        "days": [1, 2, 3, 4, 5]
    }
    assert derive_schedule("工作日每天") == {"per_week": 5} and derive_schedule("每周练两三次") == {
        "per_week": 2
    }
    assert derive_schedule("三十分钟") == {"minutes": 30} and derive_schedule("24小时健身房") == {}
    assert derive_equipment("居家锻炼") == {"place": "home"} and derive_equipment(
        "去公司健身房"
    ) == {"place": "gym"}
    gym = gear("在健身房练", id="g", data={"place": "gym"}, key="equipment")
    later = T0.replace(day=5)
    guess = Item("p", "equipment", "可能在家练", "x", "inferred", "pending", later, later,
                 data={"place": "home"}, key="equipment")  # fmt: skip
    assert equipment([gym, guess]) == frozenset(EQUIPMENT)  # 推测的不把生效的挤掉


def test_gear_page_place_from_additions_only() -> None:
    from ironm_agent.gear import read

    only = gear("家里还有个壶铃", data={"gear": ["壶铃"]})
    assert read([only])["place"] == "home" and read([only])["gear"] == ["壶铃"]
