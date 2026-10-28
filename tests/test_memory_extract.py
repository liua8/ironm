"""记忆提取：模型给出的操作要逐条核对，原话找不到、数字对不上、目标不存在的都不落库。"""

import asyncio
from datetime import UTC, datetime
from typing import Any

from ironm_agent.memory_extract import changes_of, digits, extract, handles, validate
from ironm_agent.memory_store import Item, MemoryBook
from tests.fakes import FakeLLM, down, jsonr

T0 = datetime(2026, 10, 1, tzinfo=UTC)
KNEE = Item("k1", "injury", "左膝有旧伤，深蹲蹲深了会疼", "我左膝有旧伤", "said", "active", T0, T0)
BELLS = Item("d1", "equipment", "家里有一对哑铃", "我家里有一对哑铃", "said", "active", T0, T0)
SCHED = Item("s1", "schedule", "晚上 8 点以后练，每次 45 分钟", "晚上 8 点以后", "said", "active",
             T0, T0)  # fmt: skip


def op(**kw: Any) -> dict[str, Any]:
    return {"op": "add", "inferred": False, **kw}


def check(ops: list[dict[str, Any]], user: str, answer: str = "", items: Any = ()) -> Any:
    known = handles(list(items))
    return validate({"ops": ops}, known, user, answer)


def test_quote_must_be_found_in_what_the_user_said() -> None:
    ops, rejected = check(
        [op(category="injury", content="右肩有旧伤", quote="右肩旧伤")], "我左膝有旧伤"
    )
    assert ops == [] and rejected == ["原话片段在原文里找不到"]


def test_quote_matching_ignores_spaces_and_punctuation() -> None:
    ops, _ = check(
        [op(category="equipment", content="一对哑铃，最重 20 公斤", quote="一对哑铃,最重20公斤")],
        "我家里有一对哑铃，最重 20 公斤",
    )
    assert len(ops) == 1


def test_numbers_must_come_from_the_quote() -> None:
    bad = op(category="goal", content="半年增肌 8 公斤", quote="半年内增肌 5 公斤")
    ops, rejected = check([bad], "目标是半年内增肌 5 公斤")
    assert ops == [] and rejected == ["内容里有原话里没有的数字"]


def test_chinese_numerals_in_the_quote_count() -> None:
    assert "1" in digits("能练一个小时", chinese=True)
    assert {"12", "30"} <= digits("十二点睡，三十分钟", chinese=True)
    good = op(category="schedule", content="早上 6 点能练 1 小时", quote="早上 6 点能练一个小时")
    ops, _ = check([good], "现在早上 6 点能练一个小时")
    assert len(ops) == 1


def test_advice_quote_comes_from_the_answer_not_the_user() -> None:
    advice = op(category="advice", content="全蹲换成箱式深蹲", quote="全蹲换成箱式深蹲")
    ops, _ = check([advice], "我左膝蹲深了会疼", "你先把全蹲换成箱式深蹲。")
    assert len(ops) == 1 and changes_of(ops)[0].item.origin == "advice"  # type: ignore[union-attr]
    ops, rejected = check([advice], "我想把全蹲换成箱式深蹲", "好的。")
    assert ops == [] and rejected == ["原话片段在原文里找不到"]


def test_update_supersedes_the_old_item_and_may_reuse_its_numbers() -> None:
    upd = {"op": "update", "target": "m1", "content": "晚上 8 点以后练，每次 30 分钟",
           "quote": "每次只能练 30 分钟了"}  # fmt: skip
    ops, rejected = check([upd], "最近每次只能练 30 分钟了", items=[SCHED])
    assert rejected == [] and ops[0].target is SCHED
    changes = changes_of(ops, T0)
    assert changes[0].kind == "status" and changes[0].id == "s1"
    assert changes[0].status == "superseded"
    new = changes[1].item
    assert new is not None and new.supersedes == "s1" and new.category == "schedule"


def test_resolve_marks_the_new_version_resolved() -> None:
    res = {"op": "resolve", "target": "m1", "content": "左膝旧伤已经好了", "quote": "膝盖全好了"}
    ops, _ = check([res], "膝盖全好了", items=[KNEE])
    new = changes_of(ops, T0)[1].item
    assert new is not None and new.status == "resolved" and new.supersedes == "k1"


def test_target_must_be_an_existing_item() -> None:
    ops, rejected = check(
        [{"op": "update", "target": "m9", "content": "x", "quote": "膝盖"}], "膝盖", items=[KNEE]
    )
    assert ops == [] and rejected == ["更新或解决的目标不存在"]


def test_inferred_items_wait_for_confirmation() -> None:
    guess = op(category="schedule", content="是上班族", quote="下班后才能练", inferred=True)
    ops, _ = check([guess], "我下班后才能练")
    item = changes_of(ops)[0].item
    assert item is not None and item.status == "pending" and item.origin == "inferred"


def test_same_fact_is_not_added_twice() -> None:
    again = op(category="equipment", content="家里有一对哑铃", quote="一对哑铃")
    ops, rejected = check([again, again], "我家里有一对哑铃", items=[BELLS])
    assert ops == [] and rejected == []


def test_same_item_cannot_be_changed_twice_in_one_turn() -> None:
    u = {"op": "update", "target": "m1", "content": "家里有一对哑铃，最重 15 公斤",
         "quote": "最重的是 15 公斤"}  # fmt: skip
    ops, rejected = check([u, {**u, "op": "resolve"}], "最重的是 15 公斤", items=[BELLS])
    assert len(ops) == 1 and rejected == ["同一条记忆改了两次"]


def test_unknown_category_and_bad_output_are_rejected() -> None:
    ops, rejected = check([op(category="mood", content="开心", quote="开心")], "今天很开心")
    assert ops == [] and rejected == ["未知的类别"]
    assert validate(None, {}, "x", "") == ([], ["输出不是规定格式的 JSON"])


def test_extract_end_to_end_and_model_down() -> None:
    book = MemoryBook()
    reply = jsonr({"ops": [op(category="injury", content="左膝有旧伤", quote="我左膝有旧伤")]})
    out = asyncio.run(extract(FakeLLM(lambda *_: reply), [], "我左膝有旧伤", "好的。"))
    asyncio.run(book.apply("u", out.changes))
    items = asyncio.run(book.items("u"))
    assert [(x.category, x.content, x.status) for x in items] == [
        ("injury", "左膝有旧伤", "active")
    ]
    failed = asyncio.run(extract(FakeLLM(down), [], "我左膝有旧伤", ""))
    assert failed.changes == [] and failed.failed.startswith("模型不可用")


def test_only_one_advice_per_turn() -> None:
    answer = "先把全蹲换成箱式深蹲。每组留 2 次余量。练前热身 5 分钟。"
    ops, rejected = check(
        [
            op(category="advice", content="全蹲换成箱式深蹲", quote="先把全蹲换成箱式深蹲"),
            op(category="advice", content="每组留 2 次余量", quote="每组留 2 次余量"),
        ],
        "我左膝蹲深了会疼",
        answer,
    )
    assert [o.content for o in ops] == ["全蹲换成箱式深蹲"]
    assert rejected == ["给过的建议超过每轮上限"]


def test_temporary_changes_do_not_overwrite_long_term_memory() -> None:
    """§55 需求 7：确认时说"这两周出差只有酒店健身房"：记成近期事件，原来的器械照旧。"""
    upd = {"op": "update", "target": "m1", "category": "equipment",
           "content": "这两周出差只有酒店健身房", "quote": "这两周出差只有酒店健身房"}  # fmt: skip
    ops, rejected = check([upd], "这两周出差只有酒店健身房", items=[BELLS])
    assert rejected == [] and ops[0].category == "event" and ops[0].target is None
    changes = changes_of(ops, T0)
    assert [c.kind for c in changes] == ["insert"]  # 不把"家里有一对哑铃"标为被取代
    added = op(category="schedule", content="下周旅游练不了", quote="下周旅游练不了")
    assert check([added], "下周旅游练不了")[0][0].category == "event"
    bought = op(category="equipment", content="这周买了一个壶铃", quote="这周买了一个壶铃")
    assert check([bought], "这周买了一个壶铃")[0][0].category == "equipment"
    long = {"op": "update", "target": "m1", "content": "晚上 8 点以后练，每次 30 分钟",
            "quote": "现在每次只有 30 分钟"}  # fmt: skip
    assert check([long], "现在每次只有 30 分钟", items=[SCHED])[0][0].target is SCHED
