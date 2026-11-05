"""§163 第一期独立审查后修的几处（复核 11-05）：管家出错能重试、同一天重看保留早上定的、复盘看到更多事实、
临时调整跟着计划链、预览和生效一致、作废时间、调整经历、训练中按管家定的几成。不连数据库、不调用真实模型。"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ironm_agent import review
from ironm_agent.coach_state import CoachBook, Done, Inputs, Review, record_plan
from ironm_agent.day_state import DayState
from ironm_agent.plan_layers import Temp, load, stacked
from ironm_agent.training import PlanEdit, TrainingBook, WorkoutLog, plan_content
from tests.test_coach import TODAY, plan_today, snap
from tests.test_review import facts_id, model, setup


class Broken:
    """模型调用就出错。"""

    calls = 0

    async def chat(self, *a: Any, **k: Any) -> Any:
        Broken.calls += 1
        raise RuntimeError("down")


def test_a_failed_review_is_tried_again_next_time() -> None:
    dp = setup()
    Broken.calls = 0
    first = asyncio.run(review.run("42", dp, Broken()))  # type: ignore[arg-type]
    assert first.failed and Broken.calls == 1
    asyncio.run(review.run("42", dp, Broken()))  # type: ignore[arg-type]
    assert Broken.calls == 1  # 刚失败：过一会儿才自动再试（模型一直不可用时不至于每次打开都调）
    asyncio.run(review.run("42", dp, Broken(), retry=True))  # type: ignore[arg-type]
    assert Broken.calls == 2  # 他点了重试：马上试
    state = asyncio.run(dp.store.get("42"))
    old = state.review.model_copy(update={"failed_at": state.review.failed_at - review.RETRY_AFTER})  # type: ignore[union-attr]
    asyncio.run(dp.store.save("42", state.model_copy(update={"review": old}), []))  # type: ignore[union-attr]
    asyncio.run(review.run("42", dp, Broken()))  # type: ignore[arg-type]
    assert Broken.calls == 3  # 过了间隔：失败的不当作"今天做过"
    ok, _ = model()
    good = asyncio.run(review.run("42", dp, ok, retry=True))
    assert not good.failed
    asyncio.run(review.run("42", dp, Broken(), retry=True))  # type: ignore[arg-type]
    assert Broken.calls == 3  # 做成了：点重试也不再跑


def test_a_setup_error_is_saved_as_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    dp = setup()

    async def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("db")

    monkeypatch.setattr(review, "_gather", boom)
    ok, _ = model()
    got = asyncio.run(review.run("42", dp, ok))
    state = asyncio.run(dp.store.get("42"))
    assert got.failed and state is not None and state.review is not None and state.review.failed


def test_rerun_keeps_what_was_decided_this_morning() -> None:
    dp = setup()
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe))
    f = facts_id(seen, "认出的情况：恢复不够")
    llm, _ = model({"type": "today", "ratio": 0.6, "why": "恢复不够", "basis": [f]})
    morning = asyncio.run(review.run("42", dp, llm, force=True))
    assert morning.today() is not None
    later, seen2 = model()  # 下午他说了点什么，管家重看，这次没调
    again = asyncio.run(review.run("42", dp, later, force=True))
    assert again.today() is not None and again.today().value == morning.today().value  # type: ignore[union-attr]
    assert "今天已经定过：" in seen2[0]
    asyncio.run(review.undo("42", dp, "review:today"))
    third, seen3 = model()
    asyncio.run(review.run("42", dp, third, force=True))
    assert "今天他撤销了：" in seen3[0]  # 撤销过的告诉它，别再这样调


def test_a_rerun_that_fails_keeps_the_morning_decision() -> None:
    dp = setup()
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe))
    f = facts_id(seen, "认出的情况：恢复不够")
    llm, _ = model({"type": "today", "rest": True, "why": "恢复不够", "basis": [f]})
    asyncio.run(review.run("42", dp, llm, force=True))
    got = asyncio.run(review.run("42", dp, Broken(), force=True))  # type: ignore[arg-type]
    assert not got.failed and got.today() is not None and got.today().value.get("rest")  # type: ignore[union-attr]


def test_the_review_sees_today_edits_and_rest_reasons() -> None:
    from ironm_agent.review import facts

    day = DayState(day=TODAY, edits=[PlanEdit(kind="remove", exercise="罗马尼亚硬拉")])
    logs = [WorkoutLog(day=TODAY - timedelta(days=1), done=False, rest="travel")]
    text = "\n".join(facts(Inputs(snapshot=snap(), plan=plan_today(), day=day, logs=logs), TODAY)[0].values())
    assert "今天已经改过（只改今天）：" in text and "罗马尼亚硬拉" in text
    assert "昨天没练：出差" in text


DROP_SQUAT = {"kind": "remove", "day": TODAY.isoweekday(), "exercise": "杠铃深蹲", "why": "x"}
DROP_RDL = {"kind": "remove", "day": TODAY.isoweekday(), "exercise": "罗马尼亚硬拉", "why": "x"}


def test_new_temps_are_checked_on_top_of_overlapping_ones() -> None:
    base = plan_today()
    a = Temp("a", TODAY, TODAY + timedelta(days=2), "", (DROP_SQUAT,))
    far = Temp("b", TODAY + timedelta(days=10), TODAY + timedelta(days=11), "", (DROP_RDL,))
    got = stacked(base, [a, far], TODAY + timedelta(days=1), TODAY + timedelta(days=3))
    names = [x.exercise for x in got.session_on(TODAY).items]  # type: ignore[union-attr]
    assert names == ["罗马尼亚硬拉"]  # 重叠的套上了，不重叠的没套


def test_temps_follow_the_plan_line() -> None:
    book = TrainingBook()
    d = asyncio.run(book.add_draft("42", "plan", plan_content(plan_today())))
    asyncio.run(book.confirm("42", d.id))
    root = asyncio.run(book.plan("42")).line_id  # type: ignore[union-attr]
    start = date.today() + timedelta(days=1)
    t = asyncio.run(book.add_draft("42", "temp", {"temp": {
        "start": start.isoformat(), "end": start.isoformat(), "ops": [DROP_SQUAT], "root": root}}))  # fmt: skip
    asyncio.run(book.confirm("42", t.id))
    assert len(asyncio.run(load(book, "42"))) == 1
    edit = asyncio.run(book.add_draft("42", "plan", {**plan_content(plan_today()), "ops": [DROP_RDL]}))
    asyncio.run(book.confirm("42", edit.id))
    assert len(asyncio.run(load(book, "42"))) == 1  # 按操作改的：还是同一条链
    fresh = asyncio.run(book.add_draft("42", "plan", plan_content(plan_today())))
    asyncio.run(book.confirm("42", fresh.id))
    assert asyncio.run(load(book, "42")) == []  # 新排的计划：旧链上的临时调整不再套
    asyncio.run(book.undo("42", fresh.id))
    assert len(asyncio.run(load(book, "42"))) == 1  # 撤销新计划：又回来


def test_an_unconfirmed_temp_shows_when_it_expires() -> None:
    book = TrainingBook()
    start = date.today() + timedelta(days=3)
    d = asyncio.run(book.add_draft("42", "temp", {"temp": {"start": start.isoformat(),
                                                           "end": start.isoformat(), "ops": [DROP_SQUAT]}}))  # fmt: skip
    expires = datetime.fromisoformat(d.json()["expires"])
    assert expires.astimezone().date() == start + timedelta(days=1)


def test_confirming_a_temp_goes_into_the_history() -> None:
    store = CoachBook()
    draft = {"kind": "temp", "temp": {"start": "2026-11-09", "end": "2026-11-11",
                                      "ops": [DROP_SQUAT], "lines": ["周一去掉杠铃深蹲"]}}  # fmt: skip
    assert asyncio.run(record_plan(store, "42", draft))
    [c] = asyncio.run(store.history("42"))
    assert c.change == "accepted" and "临时调整" in c.after and "杠铃深蹲" in c.after


def test_reviewing_is_not_counted_as_a_change() -> None:
    from ironm_agent.coach_state import compute, diff

    items = compute(Inputs(snapshot=snap(), plan=plan_today(), review=None), TODAY)
    assert not any(c.key == "today" for c in diff(None, items, TODAY, 1))


def test_retry_reruns_only_a_failed_review(monkeypatch: pytest.MonkeyPatch) -> None:
    from mirobody.server.auth import verify_token

    from ironm_agent import web_more

    calls: list[str] = []
    monkeypatch.setattr(review, "retry_later", lambda uid, deps: calls.append(uid))
    now: dict[str, Any] = {"r": Review(day=date.today(), failed=True)}

    async def today(_: str) -> Any:
        return now["r"]

    monkeypatch.setattr(web_more, "review_today", today)
    app = FastAPI()
    app.include_router(web_more.router)
    app.dependency_overrides[verify_token] = lambda: "42"
    c = TestClient(app)
    assert c.post("/iron/api/coach/retry").json()["status"] == "reviewing" and calls
    now["r"] = Review(day=date.today())
    assert c.post("/iron/api/coach/retry").json()["status"] == "ok" and len(calls) == 1


def test_live_start_uses_the_coach_ratio(monkeypatch: pytest.MonkeyPatch) -> None:
    from ironm_agent import web_live
    from tests.test_live import PLAN, client

    told = Review(day=date.today(), done=[Done(key="review:today", type="today", title="按六成",
                                               why="恢复不够", basis="F1", value={"ratio": 0.5})])  # fmt: skip

    async def today(_: str) -> Any:
        return told

    monkeypatch.setattr(web_live, "review_today", today)
    c, _, _ = client(monkeypatch, plan=PLAN)
    got = c.post("/iron/api/live/start", json={"exercises": [], "today_plan": True}).json()
    squat = next(x for x in got["live"]["items"] if x["exercise"] == "杠铃深蹲")
    assert len(squat["sets"]) < 3  # 计划 3 组，管家定了按五成


def test_reruns_do_not_record_the_same_decision_again() -> None:
    dp = setup()
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe))
    f = facts_id(seen, "认出的情况：恢复不够")
    llm, _ = model({"type": "today", "ratio": 0.6, "why": "恢复不够", "basis": [f]})
    added = lambda: [c for c in asyncio.run(dp.store.history("42", 200))  # noqa: E731
                     if c.key == "review:today" and c.change == "added"]  # fmt: skip
    asyncio.run(review.run("42", dp, llm, force=True))
    first = len(added())
    again, _ = model()
    asyncio.run(review.run("42", dp, again, force=True))
    assert len(added()) == first  # 早上记过的不再记
    asyncio.run(review.undo("42", dp, "review:today"))
    third, _ = model()
    asyncio.run(review.run("42", dp, third, force=True))
    assert len(added()) == first  # 撤销了的不再当新调整记一次


def test_a_rerun_that_cannot_start_keeps_the_morning_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    dp = setup()
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe))
    f = facts_id(seen, "认出的情况：恢复不够")
    llm, _ = model({"type": "today", "ratio": 0.6, "why": "恢复不够", "basis": [f]})
    asyncio.run(review.run("42", dp, llm, force=True))

    async def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("db")

    monkeypatch.setattr(review, "_gather", boom)
    got = asyncio.run(review.run("42", dp, llm, force=True))
    assert not got.failed and got.today() is not None and got.today().value["ratio"] == 0.6  # type: ignore[union-attr]


def test_a_kept_note_survives_a_failed_rerun_and_the_retry() -> None:
    dp = setup()
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe))
    f = facts_id(seen, "认出的情况：恢复不够")
    llm, _ = model({"type": "note", "text": "这周多睡一会", "why": "恢复不够", "basis": [f]})
    asyncio.run(review.run("42", dp, llm, force=True))
    broke = asyncio.run(review.run("42", dp, Broken(), force=True))  # type: ignore[arg-type]
    assert broke.failed and [d.key for d in broke.done] == ["review:note"]
    ok, _ = model()
    assert [d.key for d in asyncio.run(review.run("42", dp, ok, retry=True)).done] == ["review:note"]


def test_live_items_use_today_session_first() -> None:
    from ironm_agent.live import new_item
    from ironm_agent.training import Plan

    today = date.today().isoweekday()
    other = 1 if today != 1 else 2
    plan = Plan.model_validate({"title": "全身", "days_per_week": 2, "sessions": [
        {"day": d, "name": f"全身{d}", "items": [{"exercise": "杠铃深蹲", "sets": n, "reps": "8–10"}]}
        for d, n in sorted([(other, 4), (today, 2)])]})  # fmt: skip
    assert len(new_item("杠铃深蹲", plan, [], {}).sets) == 2


def test_an_undone_kcal_change_is_not_undone_again_on_a_rerun() -> None:
    from ironm_agent.metrics import KcalAdjust

    dp = setup()
    asyncio.run(dp.diet.apply("42", KcalAdjust(-100, TODAY - timedelta(days=30), "上个月定的")))
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe))
    f = facts_id(seen, "每日热量目标")
    llm, _ = model({"type": "kcal", "delta": -300, "why": "想减快点", "basis": [f]})
    asyncio.run(review.run("42", dp, llm, force=True))
    asyncio.run(review.undo("42", dp, "review:kcal"))
    assert asyncio.run(dp.diet.current("42")).kcal == -100  # type: ignore[union-attr]
    again, _ = model({"type": "kcal", "delta": -200, "why": "x", "basis": ["F999"]})  # 依据不对：不执行
    asyncio.run(review.run("42", dp, again, force=True))
    assert asyncio.run(dp.diet.current("42")).kcal == -100  # type: ignore[union-attr]  # 上个月的没被撤、撤掉的没回来
