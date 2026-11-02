"""当前状态统一读取、时间线（spec [2026-10-23] §97）：首页、管家消息、对话档案的"今天"一致；时间线只读。"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ironm_agent.coach_state import Change, CoachBook, Done, Item, Review, State
from ironm_agent.illness import Episode
from ironm_agent.memory_store import Item as Memory
from ironm_agent.timeline import build
from ironm_agent.training import LogItem, SetDone, WorkoutLog
from tests.fakes import jsonr

TODAY = date.today()


def home(monkeypatch: pytest.MonkeyPatch, review: Review | None, sleep: float = 4.0) -> Any:
    """首页"今天的版本"：睡得少（状态差）的一天，管家复盘按需要换。"""
    from mirobody.server.auth import verify_token

    from ironm_agent import weather, web, web_more
    from ironm_agent.casefile import Snapshot
    from ironm_agent.metrics import Profile, Readings, compute_all
    from ironm_agent.training import Plan, TrainingBook, plan_content
    from tests.test_adjust import leg_day

    book = TrainingBook()
    session = leg_day().model_copy(update={"day": TODAY.isoweekday()})
    plan = Plan.model_validate(
        {"title": "x", "days_per_week": 1, "sessions": [session.model_dump()]}
    )
    d = asyncio.run(book.add_draft("42", "plan", plan_content(plan)))
    asyncio.run(book.confirm("42", d.id))

    async def snap(user_id: str, today: date | None = None) -> Snapshot:
        p = Profile(height_cm=175, sex="male", goal="muscle", activity="moderate")
        r = Readings(sleep_hours=((TODAY, sleep),))
        return Snapshot(p, r, tuple(compute_all(r, p, TODAY)), TODAY)

    async def no_weather(user_id: str) -> None:
        return None

    async def told(_: str) -> Review | None:
        return review

    monkeypatch.setattr(web, "snapshot_for", snap)
    monkeypatch.setattr(weather, "for_user", no_weather)
    monkeypatch.setattr(web_more, "review_today", told)
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: "42"
    app.dependency_overrides[web_more.training_store] = lambda: book
    return TestClient(app).get("/iron/api/today").json()


def test_home_today_follows_the_daily_review(monkeypatch: pytest.MonkeyPatch) -> None:
    plain = home(monkeypatch, None)
    assert (
        plain["status"] == "ok" and plain["today"]["items"][0]["sets"] == 2
    )  # 没复盘：状态差照旧减半
    ratio = Review(day=TODAY, done=[Done(key="review:today", type="today", title="今天按约7成练",
                                         why="这周练多了", value={"ratio": 0.7})])  # fmt: skip
    got = home(monkeypatch, ratio)
    assert (
        got["status"] == "ok" and got["today"]["items"][0]["sets"] == 3
    )  # 4 组按七成，不再按状态差减半
    assert any("这周练多了" in x for x in got["reasons"])
    rest = Review(day=TODAY, done=[Done(key="review:today", type="today", title="今天休息",
                                        why="静息心率连着三天偏高", value={"rest": True})])  # fmt: skip
    got = home(monkeypatch, rest)
    assert got["status"] == "rest_today" and "静息心率连着三天偏高" in got["message"]


def test_chat_case_file_has_the_same_today_line(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_single_agent import single
    from tests.test_turn_flow import TODAY as FLOW  # 对话测试用的"今天"
    from tests.test_turn_flow import run

    store = CoachBook()
    item = Item(key="today", kind="today", title="今天练下肢：组数减半", why="你说今天有点累")
    state = State(version=1, day=FLOW, at=datetime.now(UTC), reason="x", items=[item])
    asyncio.run(store.save("42", state, []))
    a, s = single(lambda *_: jsonr({"answer": "好。"}), monkeypatch, old=True)
    a._coach_store = store
    run(a, "今天练什么")
    assert "今天的版本（和首页、管家消息一致）：今天练下肢：组数减半（你说今天有点累）" in s.user
    old = state.model_copy(update={"day": FLOW - timedelta(days=1)})
    asyncio.run(store.save("42", old, []))
    run(a, "今天练什么")
    assert "今天的版本" not in s.user  # 不是今天的：不写


def test_timeline_lists_everything_by_date() -> None:
    t = datetime.now(UTC)
    ago = lambda n: TODAY - timedelta(days=n)  # noqa: E731
    sick = Episode(
        symptoms=["感冒"], level="above", started=ago(10), status="resolved", ended=ago(7)
    )
    trip = Memory("m1", "event", "这周出差", "这周出差", "said", "active",
                  t - timedelta(days=5), t - timedelta(days=5), until=ago(2))  # fmt: skip
    log = WorkoutLog(day=ago(3), session="下肢",
                     items=[LogItem(exercise="杠铃深蹲", done_sets=[SetDone(reps=8, weight_kg=60)])])  # fmt: skip
    cut = Change(id="c1", at=t, day=ago(6), version=1, key="review:today", kind="review",
                 change="added", after="今天的训练按约5成练", why="感冒刚好", outcome="达到了（到期前 7 天平均 60 次/分）")  # fmt: skip
    lines = build(TODAY, 28, illness=[sick], memory=[trip], pains=[("膝盖", ago(4))],
                  workouts=[log], changes=[cut, cut])  # fmt: skip
    text = "\n".join(lines)
    assert lines[0].endswith("说感冒") and "感冒好了" in text
    assert (
        "管家：今天的训练按约5成练（原因：感冒刚好）；效果：达到了" in text
        and text.count("按约5成练") == 1
    )
    assert "近期的事：这周出差" in text and "说膝盖疼" in text and "练了：" in text
    order = [ln.split(" ", 1)[0] for ln in lines]
    assert order == sorted(
        order, key=lambda s: (int(s.split("月")[0]), int(s.split("月")[1].rstrip("日")))
    )
    assert build(TODAY, 3, illness=[sick]) == []  # 超出范围的不列


def test_agent_can_call_the_timeline(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.fakes import call
    from tests.test_single_agent import single
    from tests.test_turn_flow import run

    got: list[str] = []

    def answer(system: str, user: str, results: list[str]) -> Any:
        if not results:
            return call("timeline", days=7)
        got.extend(results)
        return jsonr({"answer": "上周没记下什么事。"})

    a, _ = single(answer, monkeypatch, old=True)
    a._coach_store = CoachBook()
    _, seen = run(a, "上周为什么给我减量了")
    assert "timeline" in seen["tools"] and got and got[0].startswith("最近 7 天")
