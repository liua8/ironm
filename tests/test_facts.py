"""记忆结构第 1 步：伤病和特殊情况结构化（spec [2026-10-23] §148）。不连数据库、不调用真实模型。"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any

from ironm_agent.casefile import injured_parts, risks
from ironm_agent.facts import derive, describe, key_of, structured
from ironm_agent.memory_extract import changes_of, validate
from ironm_agent.memory_store import Change, Item, MemoryBook
from ironm_agent.metrics import Readings
from tests.fakes import remembering
from tests.test_memory_now import items, run
from tests.test_single_agent import single

TODAY = date(2026, 11, 3)
T0 = datetime(2026, 11, 3, tzinfo=UTC)


def item(content: str, category: str = "injury", **kw: Any) -> Item:
    return Item(kw.pop("id", "i1"), category, content, content, "said", kw.pop("status", "active"),  # type: ignore[arg-type]
                kw.pop("created", T0), T0, **kw)  # fmt: skip


def test_derive_fills_parts_side_kind_and_moves_specials() -> None:
    assert derive("injury", "左膝旧伤，深蹲蹲深会疼") == (
        "injury", {"parts": ["joint.knee"], "side": "左"})  # fmt: skip
    assert derive("injury", "有高血压，在吃药") == ("special", {"codes": ["hypertension"]})
    assert derive("injury", "膝盖做了半月板手术，三个月") == (
        "injury", {"parts": ["joint.knee"], "side": "", "kind": "术后"})  # fmt: skip
    assert derive("injury", "久坐圆肩") == ("injury", {})  # 体态不是伤病
    assert derive("injury", "右手肘和髋都有点疼")[1]["parts"] == [
        "joint.hip",
        "joint.elbow",
    ]  # 补上的两个关节
    assert derive("special", "怀孕 20 周") == ("special", {"codes": ["pregnancy"]})
    assert derive("goal", "减到 70 公斤") == ("goal", {})


def test_given_fields_must_match_what_he_said() -> None:
    ok = structured("injury", {"parts": ["joint.knee"], "side": "左", "triggers": ["深蹲", "深蹲", " "],
                               "avoid": ["跳跃"], "kind": "旧伤"}, "左膝旧伤", "左膝有旧伤")  # fmt: skip
    assert ok == ("injury", {"parts": ["joint.knee"], "side": "左", "triggers": ["深蹲"],
                             "avoid": ["跳跃"], "kind": "旧伤"}, "")  # fmt: skip
    assert structured("injury", {"parts": ["膝盖"]}, "膝盖疼", "膝盖疼")[1]["parts"] == [
        "joint.knee"
    ]
    assert (
        structured("injury", {"parts": ["joint.shoulder"]}, "膝盖疼", "膝盖疼")[2]
        == "部位和原话对不上"
    )
    assert "部位要写关节" in structured("injury", {"parts": ["手指"]}, "手指疼", "手指疼")[2]
    assert "左右" in structured("injury", {"side": "上"}, "膝盖疼", "膝盖疼")[2]
    assert "只能写" in structured("injury", {"severity": "超重"}, "膝盖疼", "膝盖疼")[2]
    assert structured("special", {"code": "diabetes"}, "有糖尿病", "我有糖尿病") == (
        "special", {"codes": ["diabetes"]}, "")  # fmt: skip  # 单个 code 也认
    assert (
        structured("special", {"code": "cardiac"}, "有糖尿病", "我有糖尿病")[2]
        == "特殊情况和原话对不上"
    )
    assert structured("special", {}, "最近不舒服", "最近不舒服")[2] == "认不出是哪种特殊情况"
    assert structured("injury", {}, "有高血压", "我有高血压") == (
        "special",
        {"codes": ["hypertension"]},
        "",
    )


def test_keys_and_description() -> None:
    assert key_of("injury", {"parts": ["joint.knee"], "side": "左"}) == "injury:joint.knee:左"
    assert (
        key_of("injury", {"parts": []}) == ""
        and key_of("special", {"code": "cardiac"}) == "special:cardiac"
    )
    text = describe({"parts": ["joint.knee"], "side": "左", "kind": "旧伤", "triggers": ["深蹲"],
                     "avoid": ["跳跃"]})  # fmt: skip
    assert text == "左膝盖，旧伤，深蹲会疼，不做跳跃" and describe({"code": "pregnancy"}) == "孕期"


def test_same_key_updates_the_old_one_and_same_words_are_skipped() -> None:
    old = item("左膝疼", data={"parts": ["joint.knee"], "side": "左"}, key="injury:joint.knee:左")
    known = {"m1": old}
    op = {"op": "add", "category": "injury", "content": "左膝疼得厉害，不能跑", "quote": "左膝疼得厉害",
          "avoid": ["跑步"]}  # fmt: skip
    [got], bad = validate({"ops": [op]}, known, "我左膝疼得厉害，不能跑", "", today=TODAY)
    assert not bad and got.op == "update" and got.target is old and got.data["avoid"] == ["跑步"]
    ch = changes_of([got], T0)
    assert ch[0].kind == "status" and ch[0].id == "i1" and ch[1].item is not None
    assert ch[1].item.key == "injury:joint.knee:左" and ch[1].item.supersedes == "i1"
    same = {"op": "add", "category": "injury", "content": "左膝疼", "quote": "左膝疼"}
    assert validate({"ops": [same]}, known, "我左膝疼", "", today=TODAY) == ([], [])  # 已经记着了


def test_side_not_said_is_a_guess() -> None:
    op = {"op": "add", "category": "injury", "content": "膝盖疼", "quote": "膝盖疼", "side": "左",
          "parts": ["joint.knee"]}  # fmt: skip  # 只有字段写了左：原话里没说
    [got], _ = validate({"ops": [op]}, {}, "我膝盖疼", "", today=TODAY)
    assert got.inferred and changes_of([got], T0)[0].item.status == "pending"  # type: ignore[union-attr]


def test_injured_parts_read_fields_and_old_items_still_work() -> None:
    # 字段说是膝：内容里没有"膝"字也认得出（以前靠正则会漏）
    knee = item("髌骨那里一蹲就不舒服", data={"parts": ["joint.knee"], "side": "右"})
    assert injured_parts([knee], "") == ("joint.knee",)
    assert injured_parts([item("右肩旧伤")], "") == ("joint.shoulder",)  # 旧的没字段：照旧按句子
    assert injured_parts([item("久坐圆肩")], "") == ()
    assert injured_parts([item("手肘疼", data={"parts": []})], "") == ()  # 有字段就只信字段
    assert injured_parts([], "我髋关节疼") == ("joint.hip",)  # 这句话里说疼：补上的关节也认


def test_risks_read_specials_and_recent_surgery() -> None:
    r = Readings()
    special = item("有心脏支架", "special", data={"code": "cardiac"})
    assert [x.key for x in risks(r, [special], TODAY)] == ["cardiac"]
    op = item(
        "膝盖术后", data={"parts": ["joint.knee"], "kind": "术后"}, created=T0 - timedelta(days=30)
    )
    assert [x.key for x in risks(r, [op], TODAY)] == ["surgery"]
    old = item(
        "膝盖术后", data={"parts": ["joint.knee"], "kind": "术后"}, created=T0 - timedelta(days=120)
    )
    assert risks(r, [old], TODAY) == ()
    legacy = item("有高血压")  # 还没补字段的旧记忆：照旧按句子认
    assert [x.key for x in risks(r, [legacy], TODAY)] == ["hypertension"]
    past = item("以前怀孕时腰疼", data={"parts": ["joint.lumbar"]})  # 有字段就信字段，不再按句子认
    assert risks(r, [past], TODAY) == ()
    resolved = item("有糖尿病", "special", data={"code": "diabetes"}, status="resolved")
    assert risks(r, [resolved], TODAY) == ()


def test_old_items_get_their_fields_when_read() -> None:
    store = MemoryBook()
    rows = [item("左膝旧伤", id="a"), item("有高血压", id="b"), item("久坐圆肩", id="c"),
            item("想减到 70 公斤", "goal", id="d")]  # fmt: skip
    asyncio.run(store.apply("42", [Change("insert", item=x) for x in rows]))
    got = {x.id: x for x in asyncio.run(store.items("42"))}
    assert (
        got["a"].data == {"parts": ["joint.knee"], "side": "左"}
        and got["a"].key == "injury:joint.knee:左"
    )
    assert got["b"].category == "special" and got["b"].key == "special:hypertension"
    assert got["b"].content == "有高血压" and got["b"].evidence == "有高血压"  # 内容和原话不动
    assert got["c"].data == {} and got["d"].data == {}


def test_editing_the_words_refreshes_the_fields() -> None:
    store = MemoryBook()
    asyncio.run(store.apply("42", [Change("insert", item=item("左膝疼", id="a"))]))
    asyncio.run(store.items("42"))
    changed = asyncio.run(store.edit("42", "a", "右肩疼"))
    assert (
        changed is not None
        and changed.data["parts"] == ["joint.shoulder"]
        and changed.key.endswith(":右")
    )


def test_remember_stores_fields_and_sends_back_a_made_up_part(monkeypatch: Any) -> None:
    knee = {"op": "add", "category": "injury", "content": "左膝旧伤，深蹲蹲深会疼",
            "quote": "我左膝有旧伤，深蹲蹲深了会疼", "parts": ["joint.knee"], "side": "左",
            "kind": "旧伤", "triggers": ["深蹲"]}  # fmt: skip
    a, _ = single(remembering([knee], {"answer": "那先别蹲太深〔经验〕。"}), monkeypatch)
    run(a, "我左膝有旧伤，深蹲蹲深了会疼")
    [x] = items(a)
    assert x.data == {"parts": ["joint.knee"], "side": "左", "kind": "旧伤", "triggers": ["深蹲"]}
    assert x.key == "injury:joint.knee:左" and injured_parts([x], "") == ("joint.knee",)
    wrong = {**knee, "parts": ["joint.shoulder"]}
    a, s = single(remembering([wrong], {"answer": "好〔经验〕。"}), monkeypatch)
    run(a, "我左膝有旧伤，深蹲蹲深了会疼")
    assert items(a) == [] and "部位和原话对不上" in s.last
    special = {"op": "add", "category": "special", "content": "怀孕 16 周", "quote": "怀孕 16 周",
               "codes": ["pregnancy"]}  # fmt: skip
    a, _ = single(remembering([special], {"answer": "好〔经验〕。"}), monkeypatch)
    run(a, "我现在怀孕 16 周")
    [p] = items(a)
    assert p.category == "special" and p.data == {"codes": ["pregnancy"]}


def test_a_special_said_with_an_injury_keeps_both() -> None:
    """一句话里有部位又有特殊情况：伤病照记，特殊情况的提醒不丢（复核 11-03）。"""
    cat, data = derive("injury", "怀孕20周，最近腰疼")
    assert cat == "injury" and data["parts"] == ["joint.lumbar"] and data["codes"] == ["pregnancy"]
    assert [x.key for x in risks(Readings(), [item("怀孕20周，最近腰疼", data=data)], TODAY)] == [
        "pregnancy"
    ]
    knee = structured("injury", {"parts": ["joint.knee"], "codes": ["surgery"]}, "左膝半月板手术后三个月",
                      "左膝半月板手术后三个月")  # fmt: skip
    assert knee[0] == "injury" and knee[1]["parts"] == ["joint.knee"] and knee[1]["kind"] == "术后"
    two = derive("special", "有糖尿病和高血压")
    assert two == ("special", {"codes": ["diabetes", "hypertension"]})
    got = {
        x.key for x in risks(Readings(), [item("有糖尿病和高血压", "special", data=two[1])], TODAY)
    }
    assert got == {"diabetes", "hypertension"}


def test_about_is_not_both_sides() -> None:
    assert derive("injury", "膝盖疼了一个月左右")[1]["side"] == ""
    assert derive("injury", "左膝疼，右肩也不舒服")[1]["side"] == ""  # 几个部位有左有右：空着
    assert derive("injury", "左右膝都疼")[1]["side"] == "两侧"


def test_a_guess_does_not_replace_what_he_said() -> None:
    old = item("左膝旧伤", data={"parts": ["joint.knee"], "side": "左"}, key="injury:joint.knee:左")
    guess = {"op": "add", "category": "injury", "content": "左膝半月板可能有问题", "quote": "膝盖有点响",
             "parts": ["joint.knee"], "side": "左"}  # fmt: skip
    [got], _ = validate({"ops": [guess]}, {"m1": old}, "我膝盖有点响", "", today=TODAY)
    assert got.op == "add" and got.target is None and got.inferred  # 另记一条待确认，不顶掉生效的


def test_same_key_twice_in_one_turn_is_one_item() -> None:
    a = {"op": "add", "category": "injury", "content": "右肩旧伤", "quote": "右肩有旧伤",
         "parts": ["joint.shoulder"], "side": "右", "avoid": ["卧推"]}  # fmt: skip
    b = {"op": "add", "category": "injury", "content": "右肩推举会疼", "quote": "推举会疼",
         "parts": ["joint.shoulder"], "side": "右", "triggers": ["推举"]}  # fmt: skip
    text = "我右肩有旧伤，推举会疼"
    ops, _ = validate({"ops": [a, b]}, {}, text, "", today=TODAY)
    assert (
        len(ops) == 1 and ops[0].data["avoid"] == ["卧推"] and ops[0].data["triggers"] == ["推举"]
    )


def test_empty_parts_mean_not_given_and_updates_keep_old_fields() -> None:
    _, data, why = structured("injury", {"parts": []}, "左膝旧伤，深蹲会疼", "左膝旧伤，深蹲会疼")
    assert not why and data["parts"] == ["joint.knee"]
    old = item("左膝疼", data={"parts": ["joint.knee"], "side": "左", "triggers": ["深蹲"], "kind": "旧伤"},
               key="injury:joint.knee:左")  # fmt: skip
    op = {"op": "add", "category": "injury", "content": "左膝疼得厉害了", "quote": "左膝疼得厉害了"}
    [got], _ = validate({"ops": [op]}, {"m1": old}, "我左膝疼得厉害了", "", today=TODAY)
    assert got.op == "update" and got.data["triggers"] == ["深蹲"] and got.data["kind"] == "旧伤"


def test_clarify_lists_special_conditions_with_injuries() -> None:
    from ironm_agent.clarify import conditions
    from ironm_agent.memory_view import Recall
    from ironm_agent.metrics import Profile

    specials = [item("有高血压", "special", data={"codes": ["hypertension"]})]
    text = "\n".join(conditions(Recall.of(specials), Profile(), today=TODAY))
    assert "⑤伤病：" in text and "高血压" in text


def test_posture_with_a_special_condition_keeps_the_condition() -> None:
    assert derive("injury", "圆肩，有高血压") == ("special", {"codes": ["hypertension"]})


def test_left_and_right_knee_are_two_things() -> None:
    """有键按键算同一件事（§113 和 §148 一致）：左膝、右膝两条都留着。"""
    from ironm_agent.latest import shadowed

    left = item(
        "左膝疼", id="l", data={"parts": ["joint.knee"], "side": "左"}, key="injury:joint.knee:左"
    )
    right = item("右膝疼", id="r", data={"parts": ["joint.knee"], "side": "右"}, key="injury:joint.knee:右",
                 created=T0 + timedelta(days=1))  # fmt: skip
    assert shadowed([left, right]) == set()


def test_both_sides_only_when_said() -> None:
    assert derive("injury", "两个月前扭了左膝")[1]["side"] == "左"
    assert derive("injury", "双杠臂屈伸时右肩疼")[1]["side"] == "右"
    assert derive("injury", "两周左右膝盖疼")[1]["side"] == ""
    assert derive("injury", "双膝都疼")[1]["side"] == "两侧"
    assert derive("injury", "左肩做过手术，有点圆肩")[1]["parts"] == [
        "joint.shoulder"
    ]  # 不算只说体态


def test_merging_in_one_turn_keeps_what_he_said() -> None:
    """同一轮先交他说的更新、再交同一处的推测：留他说的那条，不变成待确认（复核 11-03）。"""
    old = item("左膝疼", data={"parts": ["joint.knee"], "side": "左"}, key="injury:joint.knee:左")
    said = {"op": "update", "target": "m1", "category": "injury", "content": "左膝好多了",
            "quote": "左膝好多了", "parts": ["joint.knee"], "side": "左"}  # fmt: skip
    guess = {"op": "add", "category": "injury", "content": "左膝可能是半月板", "quote": "膝盖有点响",
             "parts": ["joint.knee"], "side": "左"}  # fmt: skip
    [got], _ = validate(
        {"ops": [said, guess]}, {"m1": old}, "我左膝好多了，就是膝盖有点响", "", today=TODAY
    )
    assert got.content == "左膝好多了" and not got.inferred and got.target is old
    [rev], _ = validate(
        {"ops": [guess, said]}, {"m1": old}, "我左膝好多了，就是膝盖有点响", "", today=TODAY
    )
    assert (
        rev.content == "左膝好多了"
        and not rev.inferred
        and rev.op == "update"
        and rev.target is old
    )


def test_update_without_side_keeps_the_side() -> None:
    old = item("左膝疼", data={"parts": ["joint.knee"], "side": "左"}, key="injury:joint.knee:左")
    op = {
        "op": "update",
        "target": "m1",
        "category": "injury",
        "content": "膝盖好多了",
        "quote": "膝盖好多了",
    }
    [got], _ = validate({"ops": [op]}, {"m1": old}, "膝盖好多了", "", today=TODAY)
    assert got.data["side"] == "左" and got.key == "injury:joint.knee:左"


def test_a_later_word_without_side_shadows_the_older_side() -> None:
    from ironm_agent.latest import shadowed

    left = item(
        "左膝疼", id="l", data={"parts": ["joint.knee"], "side": "左"}, key="injury:joint.knee:左"
    )
    later = item("膝盖不怎么疼了", id="n", data={"parts": ["joint.knee"], "side": ""}, key="injury:joint.knee:",
                 created=T0 + timedelta(days=2))  # fmt: skip
    assert shadowed([left, later]) == {"l"}


def test_several_specials_are_one_each_and_surgery_counts_from_the_first_day() -> None:
    op = {
        "op": "add",
        "category": "special",
        "content": "有糖尿病和高血压",
        "quote": "有糖尿病和高血压",
    }
    ops, _ = validate({"ops": [op]}, {}, "我有糖尿病和高血压", "", today=TODAY)
    assert sorted(o.key for o in ops) == ["special:diabetes", "special:hypertension"]
    knee = {"op": "add", "category": "injury", "content": "左膝手术后", "quote": "左膝手术后"}
    [first], _ = validate({"ops": [knee]}, {}, "左膝手术后", "", today=TODAY - timedelta(days=80))
    assert first.data["since"] == (TODAY - timedelta(days=80)).isoformat()
    old = item("左膝手术后", data=first.data, key=first.key, created=T0 - timedelta(days=80))
    again = {
        "op": "add",
        "category": "injury",
        "content": "左膝手术后还肿",
        "quote": "左膝手术后还肿",
    }
    [upd], _ = validate(
        {"ops": [again]}, {"m1": old}, "左膝手术后还肿", "", today=TODAY + timedelta(days=20)
    )
    assert upd.data["since"] == first.data["since"]  # 更新不重新计时
    fresh = item("左膝手术后还肿", data=upd.data, created=T0 + timedelta(days=20))
    assert risks(Readings(), [fresh], TODAY + timedelta(days=20)) == ()  # 第一次记起已过 100 天
