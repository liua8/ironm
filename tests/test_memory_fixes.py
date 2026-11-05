"""记忆纠错（spec [2026-10-23] §109）：只记他说了的、问句不当事实、说结束要关掉旧的、建议会过期、一次的事不进画像。

用的是排查时看到的真实情形（改写过，不含账号信息）。不连数据库、不调用模型。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from ironm_agent import agent, memory_extract
from ironm_agent.memory_extract import asked_in, changes_of, own_part, validate
from ironm_agent.memory_layers import layers
from ironm_agent.memory_store import Item
from ironm_agent.memory_view import Recall, advice_expired

TODAY = date(2026, 11, 2)


def op(category: str, content: str, quote: str, **kw: object) -> dict[str, object]:
    return {"op": "add", "category": category, "content": content, "quote": quote, **kw}


def item(category: str, content: str, *, days_ago: int = 0, status: str = "active",
         until: date | None = None, id_: str = "") -> Item:  # fmt: skip
    at = datetime(2026, 11, 2, 9, tzinfo=UTC) - timedelta(days=days_ago)
    return Item(id_ or content[:8], category, content, content, "said", status, at, at,  # type: ignore[arg-type]
                None, until)  # fmt: skip


def check(
    raw: dict[str, object], said: str, answer: str = "好的。", known: dict[str, Item] | None = None
):  # type: ignore[no-untyped-def]
    return validate({"ops": [raw]}, known or {}, said, answer, today=TODAY)


# ---- 需求 1：只记他说了的 --------------------------------------------------------------------


def test_coach_words_are_not_recorded_as_his() -> None:
    answer = "对，今天周一，按计划练全身力量A，组数按七成。"
    ops, why = check(op("event", "今天（周一）按计划练全身力量A，组数按七成", "今天不是周一吗"),
                     "今天不是周一吗", answer)  # fmt: skip
    assert ops == [] and why == ["内容是教练说的，不是他说的"]
    answer = "今晚按计划练腿：箱式深蹲 3 组，教练已安排好动作。"
    ops, _ = check(op("event", "今晚按计划练腿，教练已安排箱式深蹲等动作", "给我安排今天的训练"),
                   "给我安排今天的训练", answer)  # fmt: skip
    assert ops == []
    answer = "肚子疼先别练，今天的腿训和骑车有氧都停了。"
    ops, _ = check(op("event", "今天肚子疼，腿训和骑车有氧都停了", "肚子疼", lasting="short"),
                   "今天肚子疼", answer)  # fmt: skip
    assert [o.content for o in ops] == ["11月2日肚子疼"]  # 他说的留下，教练的安排去掉
    ops, _ = check(op("event", "今天腿疼，位置和疼痛分数还没说", "我腿疼"), "我腿疼")
    assert [o.content for o in ops] == ["11月2日腿疼"]  # 旁白去掉


def test_his_own_words_are_kept_whole() -> None:
    said = "工作日只能晚上 8 点以后练，每次最多 45 分钟"
    ops, _ = check(op("schedule", said, said), said, f"好的，{said}，我按这个排。")
    assert [o.content for o in ops] == [said]
    assert own_part("这周整体训练量调轻，每次训练组数按七成", "这周整体轻一点",
                    "这周每次训练组数按七成") == "这周整体训练量调轻"  # fmt: skip


# ---- 需求 2：问句不当事实 ----------------------------------------------------------------------


def test_facts_from_questions_wait_for_confirmation() -> None:
    answer = "肌酐偏高常见原因是……建议复查确认原因。"
    ops, _ = check(
        op("injury", "肌酐含量偏高，需复查确认原因", "肌酐含量高了"), "肌酐含量高了怎么办", answer
    )
    assert (
        len(ops) == 1 and ops[0].inferred and ops[0].content == "肌酐含量偏高"
    )  # 待确认，推测的去掉
    assert changes_of(ops)[0].item.status == "pending"  # type: ignore[union-attr]
    ops, _ = check(op("injury", "左膝有旧伤", "我左膝有旧伤"), "我左膝有旧伤，深蹲会疼")
    assert not ops[0].inferred  # 陈述照常
    ops, _ = check(op("event", "吃了布洛芬", "我吃了布洛芬"), "我吃了布洛芬能练习吗")
    assert not ops[0].inferred  # 问句里顺带说的近况照常记
    assert asked_in("久坐圆肩", "久坐圆肩怎么改善") and not asked_in(
        "乳糖不耐受", "我乳糖不耐受。早餐吃什么？"
    )


# ---- 需求 3：说结束要关掉旧的 ------------------------------------------------------------------


def test_saying_it_ended_resolves_the_open_items() -> None:
    trip = item("event", "出差期间不练了，暂停训练", until=TODAY + timedelta(days=3), id_="trip")
    ask = item("followup", "出差回来前一天跟教练说一声", until=TODAY + timedelta(days=3), id_="ask")
    knee = item("injury", "左膝旧伤", id_="knee")
    known = {"m1": trip, "m2": ask, "m3": knee}
    raws = [op("event", c, "不出差了") for c in ("出差结束，恢复训练", "出差取消，周二不再外出",
                                                "已结束出差，不再出差", "出差结束，不再需要补练安排")]  # fmt: skip
    ops, _ = validate({"ops": raws}, known, "不出差了", "好，那就照常练。", today=TODAY)
    assert sorted((o.op, o.target.id) for o in ops if o.target) == [
        ("resolve", "ask"),
        ("resolve", "trip"),
    ]
    assert all(o.op == "resolve" for o in ops)  # 4 条"出差结束"一条也不新增
    sick = item("event", "从昨天起身体不舒服，今天还没好", until=TODAY, id_="sick")
    ops, _ = validate({"ops": [op("event", "身体恢复", "身体好了")]}, {"m1": sick}, "身体好了", "好。",
                      today=TODAY)  # fmt: skip
    assert [(o.op, o.target.id if o.target else "") for o in ops] == [("resolve", "sick")]
    belly = item("event", "今天肚子疼", id_="belly")
    ops, _ = validate({"ops": [op("event", "肚子已经不疼了", "肚子不疼")]}, {"m1": belly}, "今天肚子不疼啊",
                      "好。", today=TODAY)  # fmt: skip
    assert [o.op for o in ops] == ["resolve"]
    upd = {"op": "update", "target": "m1", "category": "event", "content": "出差取消了",
           "quote": "不出差了"}  # fmt: skip
    ops, _ = validate({"ops": [upd]}, {"m1": trip}, "不出差了", "好。", today=TODAY)
    assert [(o.op, o.target.id if o.target else "") for o in ops] == [("resolve", "trip")]
    assert changes_of(ops)[1].item.status == "resolved"  # type: ignore[union-attr]  # 更新成结束 = 已解决
    ops, _ = validate(
        {"ops": [op("event", "出差结束", "不出差了")]}, {}, "不出差了", "好。", today=TODAY
    )
    assert ops == []  # 没有可关的：不记


# ---- 需求 4：建议会过期、会被取代 ---------------------------------------------------------------


def test_advice_expires() -> None:
    tonight = check(op("advice", "今晚高脚杯深蹲先空手做2组", "今晚高脚杯深蹲先空手做2组"), "怎么练",
                    "今晚高脚杯深蹲先空手做2组")[0][0]  # fmt: skip
    assert tonight.until == TODAY
    week = check(
        op("advice", "这周训练量按七成", "这周训练量按七成"), "怎么练", "这周训练量按七成"
    )[0][0]
    assert week.until == date(2026, 11, 8)
    later = check(op("advice", "下周加一组深蹲", "下周加一组深蹲"), "怎么练", "下周加一组深蹲")[0][
        0
    ]
    assert later.until is None
    old_tonight = item("advice", "今晚先空手做2组", days_ago=1)
    dated = item("advice", "11月1日全身力量A把划船加到3组", days_ago=1)
    fresh = item("advice", "深蹲降到不疼的深度", days_ago=3)
    stale = item("advice", "深蹲降到不疼的深度", days_ago=15)
    assert advice_expired(old_tonight, TODAY) and advice_expired(dated, TODAY)
    assert not advice_expired(fresh, TODAY) and advice_expired(stale, TODAY)
    assert not advice_expired(item("advice", "今晚先空手做2组"), TODAY)  # 当天还用


def test_expired_advice_is_not_shown_to_the_coach() -> None:
    old = item("advice", "今晚先空手做2组", days_ago=1, id_="old")
    keep = item("advice", "深蹲降到不疼的深度", days_ago=3, id_="keep")
    shown = "\n".join(layers([old, keep], TODAY).episodes)
    assert "深蹲降到不疼的深度" in shown and "空手做2组" not in shown
    assert [x.id for x in Recall.of([old, keep], datetime(2026, 11, 2, 12, tzinfo=UTC)).items] == [
        "keep"
    ]


def test_newer_advice_on_the_same_amount_replaces_the_older() -> None:
    old = item("advice", "每天少吃约200千卡，蛋白质按111–138克吃", days_ago=10, id_="old")
    ops, _ = check(op("advice", "每天蛋白质108–134克，分3–4餐", "每天蛋白质108–134克，分3–4餐"),
                   "要吃多少蛋白", "每天蛋白质108–134克，分3–4餐", {"m1": old})  # fmt: skip
    assert ops[0].op == "update" and ops[0].target is not None and ops[0].target.id == "old"
    other = item("advice", "深蹲降到不疼的深度", id_="sq")
    ops, _ = check(op("advice", "每天蛋白质108–134克", "每天蛋白质108–134克"), "蛋白", "每天蛋白质108–134克",
                   {"m1": other})  # fmt: skip
    assert ops[0].op == "add"  # 不同的事不取代


# ---- 需求 5：一次的事不进画像 ------------------------------------------------------------------


def test_one_off_things_do_not_enter_the_profile() -> None:
    lift = check(op("level", "今天杠铃卧推60公斤做了5次", "今天杠铃卧推60公斤做了5次"),
                 "今天杠铃卧推60公斤做了5次")[0][0]  # fmt: skip
    assert lift.category == "event" and lift.until == TODAY  # 没标长短也不进训练水平
    meal = check(op("diet", "早餐吃了一个苹果", "早上一个苹果"), "早上一个苹果")[0][0]
    assert meal.category == "event" and meal.until == TODAY
    habit = check(
        op("diet", "每天早上喝一勺乳清蛋白", "每天早上喝一勺乳清蛋白"),
        "我最近开始每天早上喝一勺乳清蛋白",
    )[0][0]
    assert habit.category == "diet"


def test_both_memory_instructions_have_the_rules() -> None:
    extract = memory_extract._PROMPT
    assert "问句里带出的事不等于他有这件事" in extract and '不新增"已结束"' in extract
    assert "用 update 指向那条建议" in extract and "分开记" in extract
    from ironm_agent.actions import REMEMBER_SCHEMA

    turn = REMEMBER_SCHEMA["function"]["description"]  # 管家记记忆的写法在工具说明里（§145）
    assert (
        "remember" in agent.RECORD_INLINE  # 默认回答后在后台记（§166），切回当场记时才提
        and "问句带出的不算" in turn
        and "你的安排不写进去" in turn
        and '不新增"已结束"' in turn
    )
