"""打卡分享卡和周报（spec [2026-11-03] §147）：数按规则算对；没记录的项不写；对话页的周报消息点掉这周不再出。
不连网络、不连数据库、不调用模型。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ironm_agent.share import records, volume, week_report, workout_card
from ironm_agent.training import LogItem, Plan, SetDone, TrainingBook, WorkoutLog, week_start

TODAY = date.today()
LAST_MON = week_start(TODAY) - timedelta(days=7)


def lift(day: date, kg: float, reps: int, n: int = 2, **kw: Any) -> WorkoutLog:
    sets = [SetDone(reps=reps, weight_kg=kg) for _ in range(n)]
    return WorkoutLog(day=day, items=[LogItem(exercise="杠铃卧推", done_sets=sets)], **kw)


def test_card_numbers() -> None:
    old = lift(LAST_MON - timedelta(days=7), 60, 8)
    log = WorkoutLog(day=LAST_MON, session="上肢", minutes=50, rpe=7, items=[
        LogItem(exercise="杠铃卧推", done_sets=[SetDone(reps=8, weight_kg=62.5), SetDone(reps=6, weight_kg=62.5)]),
        LogItem(exercise="平板支撑", done_sets=[SetDone(reps=1, seconds=45)]),  # 计时的：不算重量
        LogItem(exercise="哑铃划船", sets=3, reps="10", weight_kg=20),  # 没逐组记：按计划组数算
    ])  # fmt: skip
    card = workout_card(log, [old, log], streak_days=4)
    assert card["session"] == "上肢" and card["minutes"] == 50 and card["sets"] == 6
    assert card["volume_kg"] == 62.5 * 8 + 62.5 * 6 + 20 * 10 * 3
    assert card["records"] == [{"exercise": "杠铃卧推", "weight_kg": 62.5, "reps": 8}]
    assert (
        card["streak_days"] == 4 and "weight" not in card and "body_fat" not in card
    )  # 不放身体数据
    assert records(old, [old, log]) == []  # 以前没做过的不算破纪录
    assert volume(WorkoutLog(day=TODAY, items=[LogItem(exercise="跑步机慢跑", sets=1)])) == 0


def test_week_report_counts_last_week_only() -> None:
    plan = Plan.model_validate({"title": "x", "days_per_week": 2, "sessions": [
        {"day": 1, "name": "A", "items": [{"exercise": "杠铃卧推", "sets": 2, "reps": "8"}]},
        {"day": 4, "name": "B", "items": [{"exercise": "杠铃卧推", "sets": 2, "reps": "8"}]}]})  # fmt: skip
    logs = [
        lift(LAST_MON - timedelta(days=3), 60, 8),  # 上上周
        lift(LAST_MON, 60, 8, minutes=40, rpe=6),
        lift(LAST_MON + timedelta(days=3), 65, 6, minutes=50, rpe=8),
        lift(LAST_MON + timedelta(days=7), 70, 5),  # 本周：不算
    ]
    weights = [
        (LAST_MON, 70.2),
        (LAST_MON + timedelta(days=6), 69.6),
        (LAST_MON + timedelta(days=8), 60.0),
    ]
    day_kcal = {
        LAST_MON: 2000.0,
        LAST_MON + timedelta(days=1): 2150.0,
        LAST_MON + timedelta(days=2): 2600.0,
    }
    r = week_report(LAST_MON, plan, LAST_MON - timedelta(days=30), logs, weights=weights,
                    day_kcal=day_kcal, kcal_target=2000, tips=["这周睡得少：先把睡眠补上。"])  # fmt: skip
    assert r["done"] == 2 and r["planned"] == 2 and r["minutes"] == 90 and r["sets"] == 4
    assert r["volume_kg"] == 60 * 8 * 2 + 65 * 6 * 2 and r["rpe"] == 7.0
    assert r["records"] == [{"exercise": "杠铃卧推", "weight_kg": 65, "reps": 6}]
    assert r["weight"] == {"from": 70.2, "to": 69.6, "change": -0.6}
    assert r["diet"] == {"logged": 3, "on_target": 2}  # 2150 在 10% 以内，2600 不在
    assert r["focus"] == "这周睡得少：先把睡眠补上。"
    empty = week_report(LAST_MON, None, None, [])
    assert (
        empty["done"] == 0
        and empty["planned"] is None
        and empty["weight"] is None
        and empty["diet"] is None
    )
    assert empty["rpe"] is None and empty["focus"] == "照计划来，保持节奏。"


def _client(
    monkeypatch: pytest.MonkeyPatch, logs: list[WorkoutLog]
) -> tuple[TestClient, TrainingBook, Any]:
    from mirobody.server.auth import verify_token

    from ironm_agent import brief, web, web_more
    from ironm_agent.casefile import Snapshot
    from ironm_agent.checkin_photo import PhotoBook
    from ironm_agent.coach_state import CoachBook, Deps
    from ironm_agent.illness import IllnessBook
    from ironm_agent.meals import MealBook
    from ironm_agent.metrics import Readings

    book, coach = TrainingBook(), CoachBook()
    book.seed("42", None, tuple(logs))

    async def snap(user_id: str, today: date | None = None) -> Snapshot:
        return Snapshot(
            readings=Readings(weight=((LAST_MON, 70.0), (LAST_MON + timedelta(days=5), 69.5))),
            today=today or TODAY,
        )

    monkeypatch.setattr(web, "snapshot_for", snap)
    monkeypatch.setattr(brief, "weekly_review", lambda *a, **k: {"tips": []})
    monkeypatch.setattr(
        web_more,
        "coach_deps",
        lambda: Deps(snapshot=snap, training=book, pain=None, goals=None, diet=None, store=coach),
    )
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: "42"
    app.dependency_overrides[web_more.training_store] = lambda: book
    app.dependency_overrides[web_more.meal_store] = MealBook
    app.dependency_overrides[web_more.illness_store] = IllnessBook
    app.dependency_overrides[web_more.photo_store] = PhotoBook
    return TestClient(app), book, coach


def test_share_and_report_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    from ironm_agent.coach_state import State

    c, book, coach = _client(
        monkeypatch,
        [lift(LAST_MON, 60, 8, minutes=30), lift(LAST_MON + timedelta(days=2), 62.5, 8)],
    )
    rows = book._logs["42"]
    got = c.get(f"/iron/api/share/workout/{rows[-1].id}").json()
    assert (
        got["records"][0]["weight_kg"] == 62.5
        and got["photo"] is False
        and got["volume_kg"] == 62.5 * 8 * 2
    )
    assert c.get("/iron/api/share/workout/nope").status_code == 404
    r = c.get("/iron/api/report/week").json()
    assert r["from"] == LAST_MON.isoformat() and r["done"] == 2 and r["weight"]["change"] == -0.5
    assert r["seen"] is False
    assert c.post("/iron/api/report/week/seen").json() == {
        "ok": False
    }  # 还没有方案：记不下，消息照出
    coach.states["42"] = State(version=1, day=TODAY, at=datetime.now(UTC), reason="x", items=[])
    assert c.post("/iron/api/report/week/seen").json() == {"ok": True}
    assert c.get("/iron/api/report/week").json()["seen"] is True  # 这周不再出


def test_page_wiring() -> None:
    """打卡成功后弹分享卡；练完的卡和时间线里能打开；战绩页最上面是周报；对话页有 IronM 的周报消息，点掉记下。"""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "ironm_agent" / "web" / "app.js").read_text(
        encoding="utf-8"
    )
    assert "setTimeout(() => shareSheet(r.workout.id)" in src  # 打卡
    assert (
        src.count("shareSheet(r.workout.id)") >= 2 and "shareSheet(x.id)" in src
    )  # 练完的卡、时间线
    assert "if (rep) view.append(weekReport(rep));" in src
    assert "weekMsgView(weekMsg)" in src and "/iron/api/report/week/seen" in src
    card = src[src.index("function workoutCard(d)") : src.index("async function shareSheet(")]
    assert "weight" not in card.replace("weight_kg", "") and "body_fat" not in card  # 不放身体数据
