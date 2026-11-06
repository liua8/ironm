"""管家的建议有生命周期（spec [2026-10-23] §182 需求 4 其余）：带出现日期和到期日（默认 7 天，预览类跟着预览），
同一件事新的替换旧的，"暂不"当天不再提，"不用这样调"、撤销、取消预览后同一件事 14 天内不再提（管家看到"他 X 天前拒绝过"）。
不连数据库、不调用真实模型。"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import Any

from ironm_agent import review
from ironm_agent.coach_state import REFUSE_DAYS, SUGGEST_DAYS, State, decide, evaluate, pending
from ironm_agent.metrics import KcalAdjust
from tests.fakes import FakeLLM, call, jsonr
from tests.test_coach import TODAY
from tests.test_review import facts_id, model, setup

TEMP = "propose_temporary_change"


def temp_model(
    start_in: int, exercise: str = "罗马尼亚硬拉"
) -> tuple[FakeLLM, list[str], list[str]]:
    """假管家：提一次临时调整（从 start_in 天后起一天，去掉一个动作）；seen 记它看到的事实，said 记工具结果。"""
    seen: list[str] = []
    said: list[str] = []

    def answer(stage: Any, messages: Any, tools: Any) -> Any:
        seen.append(str(messages[1]["content"]))
        results = [str(m["content"]) for m in messages if m.get("role") == "tool"]
        said.extend(x for x in results if x not in said)
        if tools and not results:
            f = facts_id(seen, "当前计划")
            start = TODAY + timedelta(days=start_in)
            op = {"kind": "remove", "day": start.isoweekday(), "exercise": exercise, "why": "出差"}
            return call(TEMP, start=start.isoformat(), end=start.isoformat(), ops=[op], why="出差那天少练一个",
                        basis=[f])  # fmt: skip
        return jsonr({"summary": "提了临时调整"})

    return FakeLLM(answer), seen, said


def plan_on_every_day() -> Any:
    """每天都有同一节课：哪天开始的临时调整都套得上。"""
    from ironm_agent.training import Plan, TrainingBook, plan_content

    p = Plan.model_validate({"title": "x", "days_per_week": 7, "sessions": [
        {"day": d, "name": f"全身{d}", "items": [{"exercise": "杠铃深蹲", "sets": 4, "reps": "6–8"},
                                               {"exercise": "罗马尼亚硬拉", "sets": 3, "reps": "8–10"}]}
        for d in range(1, 8)]})  # fmt: skip
    book = TrainingBook()
    d = asyncio.run(book.add_draft("42", "plan", plan_content(p)))
    asyncio.run(book.confirm("42", d.id))
    dp = setup()
    dp.training = book
    return dp


def state(dp: Any) -> State:
    got = asyncio.run(dp.store.get("42"))
    assert got is not None
    return got


def note(dp: Any, text: str, day: Any) -> None:
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe, today=day, force=True))
    f = facts_id(seen, "静息心率：和你自己比")
    llm, _ = model({"type": "note", "text": text, "why": "睡得少", "basis": [f]})
    asyncio.run(review.run("42", dp, llm, today=day, force=True))


def test_a_note_hangs_for_seven_days_then_is_withdrawn() -> None:
    dp = setup()
    note(dp, "这周早点睡", TODAY)
    d = state(dp).review.done[0]  # type: ignore[union-attr]
    assert d.appeared == TODAY and d.expires == TODAY + timedelta(days=SUGGEST_DAYS)
    for n in (1, 3, SUGGEST_DAYS - 1):  # 第二天以后：今天的复盘还没提，前几天提的照样挂着
        s, _ = asyncio.run(evaluate("42", dp, reason="x", today=TODAY + timedelta(days=n)))
        x = s.item("review:note")
        assert (
            x is not None and x.title == "这周早点睡" and x.value["appeared"] == TODAY.isoformat()
        )
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe, today=TODAY + timedelta(days=3), force=True))
    assert "还挂着的建议：这周早点睡" in seen[0]  # 管家看到还挂着的建议
    s, _ = asyncio.run(evaluate("42", dp, reason="x", today=TODAY + timedelta(days=SUGGEST_DAYS)))
    assert s.item("review:note") is None and s.carried == []  # 到期撤了


def test_a_newer_suggestion_on_the_same_topic_replaces_the_older() -> None:
    dp = setup()
    note(dp, "这周早点睡", TODAY)
    note(dp, "睡前别看手机", TODAY + timedelta(days=2))
    s = state(dp)
    assert [x.title for x in s.items if x.key == "review:note"] == ["睡前别看手机"]
    s, _ = asyncio.run(evaluate("42", dp, reason="x", today=TODAY + timedelta(days=3)))
    assert [x.title for x in s.items if x.key == "review:note"] == ["睡前别看手机"]  # 旧的不再回来


def test_a_temp_proposal_stays_pending_until_its_preview_expires_and_a_newer_one_replaces_it() -> (
    None
):
    dp = plan_on_every_day()
    llm, _, _ = temp_model(4)
    first = asyncio.run(review.run("42", dp, llm, today=TODAY, force=True))
    [d] = first.done
    assert d.key == "review:temp" and d.expires == TODAY + timedelta(
        days=5
    )  # 过了开始那天预览就作废
    for n in (1, 4):
        s, _ = asyncio.run(evaluate("42", dp, reason="x", today=TODAY + timedelta(days=n)))
        assert [x.key for x in pending(s, TODAY + timedelta(days=n))] == ["review:temp"]
    s, _ = asyncio.run(evaluate("42", dp, reason="x", today=TODAY + timedelta(days=5)))
    assert pending(s, TODAY + timedelta(days=5)) == []
    # 第二天又提了同一件事（临时调整）：新的替换旧的，旧的预览作废
    dp2 = plan_on_every_day()
    asyncio.run(review.run("42", dp2, temp_model(4)[0], today=TODAY, force=True))
    old_draft = str(state(dp2).review.done[0].value["draft"])  # type: ignore[union-attr]
    asyncio.run(
        review.run(
            "42", dp2, temp_model(5, "杠铃深蹲")[0], today=TODAY + timedelta(days=1), force=True
        )
    )
    s = state(dp2)
    [p] = pending(s, TODAY + timedelta(days=1))
    assert "杠铃深蹲" in p.title and s.carried == []
    assert asyncio.run(dp2.training.draft("42", old_draft)).state == "cancelled"  # type: ignore[union-attr]


def test_later_hides_it_for_that_day_only() -> None:
    dp = plan_on_every_day()
    asyncio.run(review.run("42", dp, temp_model(4)[0], today=TODAY, force=True))
    day1 = TODAY + timedelta(days=1)
    asyncio.run(evaluate("42", dp, reason="x", today=day1))
    assert asyncio.run(decide(dp.store, "42", "review:temp", "later", today=day1)) is not None
    assert pending(state(dp), day1) == []
    s, _ = asyncio.run(evaluate("42", dp, reason="x", today=day1 + timedelta(days=1)))
    assert [x.key for x in pending(s, day1 + timedelta(days=1))] == ["review:temp"]


def test_undo_of_an_earlier_proposal_suppresses_the_topic_for_two_weeks() -> None:
    dp = plan_on_every_day()
    asyncio.run(review.run("42", dp, temp_model(6)[0], today=TODAY, force=True))
    draft = str(state(dp).review.done[0].value["draft"])  # type: ignore[union-attr]
    day2 = TODAY + timedelta(days=2)
    done = asyncio.run(review.undo("42", dp, "review:temp", today=day2))  # 前天提的，今天说不用
    assert done is not None and asyncio.run(dp.training.draft("42", draft)).state == "cancelled"  # type: ignore[union-attr]
    s = state(dp)
    assert pending(s, day2) == [] and s.refused["review:temp"].day == day2
    day5 = TODAY + timedelta(days=5)
    llm, seen, said = temp_model(8)
    got = asyncio.run(review.run("42", dp, llm, today=day5, force=True))
    assert got.done == [] and any(
        x.startswith("没执行：他 3 天前拒绝过") for x in said
    )  # 代码不出，不报错
    assert "他 3 天前拒绝过：" in seen[0]  # 管家看到他拒绝过
    assert pending(state(dp), day5) == []
    later = day2 + timedelta(days=REFUSE_DAYS)
    llm, seen, _ = temp_model(REFUSE_DAYS + 4)
    assert asyncio.run(
        review.run("42", dp, llm, today=later, force=True)
    ).done  # 过了 14 天可以再提
    assert "拒绝过" not in seen[0]


def test_an_undone_kcal_change_is_not_made_again_within_two_weeks() -> None:
    dp = setup()
    asyncio.run(dp.diet.apply("42", KcalAdjust(-100, TODAY - timedelta(days=30), "上个月定的")))
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe))
    f = facts_id(seen, "每日热量目标")
    llm, _ = model({"type": "kcal", "delta": -200, "why": "想减快点", "basis": [f]})
    asyncio.run(review.run("42", dp, llm, force=True))
    asyncio.run(review.undo("42", dp, "review:kcal"))
    day3 = TODAY + timedelta(days=3)
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe, today=day3, force=True))
    f = facts_id(seen, "每日热量目标")
    again, _ = model({"type": "kcal", "delta": -150, "why": "再试试", "basis": [f]})
    assert asyncio.run(review.run("42", dp, again, today=day3, force=True)).done == []
    assert asyncio.run(dp.diet.current("42")).kcal == -100  # type: ignore[union-attr]


def test_undoing_today_does_not_block_the_next_days() -> None:
    """今天怎么练只管今天：撤销了不算拒绝，明天管家照样能定。"""
    dp = setup()
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe))
    f = facts_id(seen, "静息心率：和你自己比")
    asyncio.run(
        review.run(
            "42",
            dp,
            model({"type": "today", "ratio": 0.6, "why": "x", "basis": [f]})[0],
            force=True,
        )
    )
    asyncio.run(review.undo("42", dp, "review:today"))
    assert state(dp).refused == {}
    day1 = TODAY + timedelta(days=1)
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe, today=day1, force=True))
    f = facts_id(seen, "静息心率：和你自己比")
    llm, _ = model({"type": "today", "ratio": 0.7, "why": "x", "basis": [f]})
    assert asyncio.run(review.run("42", dp, llm, today=day1, force=True)).today() is not None


def test_cancelling_the_preview_counts_as_no() -> None:
    dp = plan_on_every_day()
    asyncio.run(review.run("42", dp, temp_model(4)[0], today=TODAY, force=True))
    draft = str(state(dp).review.done[0].value["draft"])  # type: ignore[union-attr]
    asyncio.run(dp.training.cancel("42", draft))  # 他在卡片上点了取消
    assert asyncio.run(review.declined_draft("42", dp, draft, today=TODAY))
    s = state(dp)
    assert "review:temp" in s.refused and pending(s, TODAY) == []
    assert not asyncio.run(review.declined_draft("42", dp, "nope", today=TODAY))


def test_an_old_stored_state_without_the_new_fields_still_loads_and_rolls_over() -> None:
    day = TODAY - timedelta(days=2)
    raw = {"version": 3, "day": day.isoformat(), "at": "2026-11-01T00:00:00Z", "reason": "x", "items": [],
           "review": {"day": day.isoformat(), "done": [
               {"key": "review:ask", "type": "ask", "title": "最近睡得怎么样？"},
               {"key": "review:today", "type": "today", "title": "今天休息", "value": {"rest": True}}]}}  # fmt: skip
    old = State.model_validate_json(json.dumps(raw))
    assert old.carried == [] and old.refused == {} and old.review.done[0].appeared is None  # type: ignore[union-attr]
    dp = setup()
    asyncio.run(dp.store.save("42", old, []))
    s, _ = asyncio.run(evaluate("42", dp, reason="x", today=TODAY))
    [c] = s.carried  # 今天怎么练不挂；问的那句按那次复盘的日子算起
    assert (
        c.key == "review:ask"
        and c.appeared == day
        and c.expires == day + timedelta(days=SUGGEST_DAYS)
    )
    assert s.item("review:ask") is not None and s.item("review:today") is None


def test_the_page_gets_an_earlier_proposal_and_cancelling_it_there_counts_as_no(
    monkeypatch: Any,
) -> None:
    """首页"按复盘调整"也拿得到前几天提的、还挂着的预览；在卡片上点取消（取消接口）记成他说了不用。"""
    from ironm_agent import web_more

    dp = plan_on_every_day()
    asyncio.run(review.run("42", dp, temp_model(4)[0], today=TODAY, force=True))
    day1 = TODAY + timedelta(days=1)
    monkeypatch.setattr(web_more, "coach_deps", lambda: dp)
    monkeypatch.setattr(web_more, "date", type("D", (), {"today": staticmethod(lambda: day1)}))
    out = asyncio.run(web_more._checkup_proposal("42", dp.training))
    assert out is not None and out["status"] == "ok" and out["draft"]["kind"] == "temp"
    gone = asyncio.run(dp.training.cancel("42", out["draft"]["id"]))
    assert gone is not None
    monkeypatch.setattr(review, "date", type("D", (), {"today": staticmethod(lambda: day1)}))
    asyncio.run(web_more.coach_declined("42", gone.json()))
    assert state(dp).refused["review:temp"].day == day1


def test_the_review_sees_long_unconfirmed_memories_with_their_dates() -> None:
    """§182：哪些记忆很久没确认（带上次确认的日期）在管家复盘看到的事实里；问不问由管家定，代码不生成该问的。"""
    from ironm_agent.memory_store import Change, MemoryBook
    from tests.test_memory_layers import item

    book = MemoryBook()
    old = TODAY - timedelta(days=120)
    gear = item("e", "equipment", "家里有一对 10 公斤哑铃", old)
    asyncio.run(book.apply("42", [Change("insert", item=gear)]))
    dp = setup()
    dp.memory = book
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe))
    assert (
        f"很久没确认的记忆：器械与场地：家里有一对 10 公斤哑铃（上次确认 {old.month}月{old.day}日，120 天前）"
        in seen[0]
    )
    assert not [x for x in asyncio.run(book.items("42")) if x.category == "followup"]
