"""训练记录器（spec [2026-10-23] §71）：开始、预先填好、每组记重量次数用时、存服务端、结束存成训练记录。"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ironm_agent.live import IDLE, Live, LiveBook, LiveItem, LiveSet, to_log
from ironm_agent.memory_store import MemoryBook
from ironm_agent.training import LogItem, Plan, SetDone, TrainingBook, WorkoutLog

TODAY = date.today()
PLAN = Plan.model_validate({"title": "全身", "days_per_week": 1, "sessions": [{
    "day": TODAY.isoweekday(), "name": "全身 A", "minutes": 45,
    "items": [{"exercise": "杠铃深蹲", "sets": 3, "reps": "8–10"}, {"exercise": "平板支撑", "sets": 2, "reps": "30 秒"}],
}]})  # fmt: skip


def client(
    monkeypatch: pytest.MonkeyPatch, plan: Plan | None = None, logs: tuple[WorkoutLog, ...] = ()
) -> tuple[TestClient, TrainingBook, LiveBook]:
    from mirobody.server.auth import verify_token

    from ironm_agent import web, web_live, web_more
    from ironm_agent.illness import IllnessBook

    book, lives, memory, ill = TrainingBook(), LiveBook(), MemoryBook(), IllnessBook()
    book.seed("42", plan, logs)
    monkeypatch.setattr(web, "refresh_later", lambda *a: None)
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: "42"
    app.dependency_overrides[web.training_store] = lambda: book
    app.dependency_overrides[web_more.training_store] = lambda: book
    app.dependency_overrides[web.memory_store] = lambda: memory
    app.dependency_overrides[web_more.illness_store] = lambda: ill
    app.dependency_overrides[web_live.live_store] = lambda: lives
    return TestClient(app), book, lives


def done(item: dict[str, Any], i: int, **kw: Any) -> None:
    item["sets"][i] |= {"done": True, "at": datetime.now().isoformat(), **kw}


def test_start_from_move_and_prefill_from_last_time(monkeypatch: pytest.MonkeyPatch) -> None:
    last = WorkoutLog(day=TODAY - timedelta(days=3), items=[LogItem(exercise="哑铃卧推", done_sets=[
        SetDone(reps=10, weight_kg=20), SetDone(reps=9, weight_kg=20)])])  # fmt: skip
    c, _, _ = client(monkeypatch, logs=(last,))
    got = c.post("/iron/api/live/start", json={"exercises": ["哑铃卧推"]}).json()
    [item] = got["live"]["items"]
    assert [(s["weight_kg"], s["reps"]) for s in item["sets"]] == [(20, 10), (20, 9)]  # 逐组照上次填
    assert item["sets"][0]["seconds"] is None and not item["sets"][0]["done"]
    assert item["rest"] == 90 and item["target"].startswith("上次 20×10")
    again = c.post("/iron/api/live/start", json={"exercises": ["杠铃深蹲"]}).json()
    assert again["live"]["id"] == got["live"]["id"]  # 已有进行中的：接着练，不另开


def test_start_from_today_plan_with_targets_timed_and_barbell_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c, _, _ = client(monkeypatch, plan=PLAN)
    got = c.post("/iron/api/live/start", json={"today_plan": True}).json()["live"]
    squat, plank = got["items"]
    assert got["session"] == "全身 A" and [x["exercise"] for x in got["items"]] == [
        "杠铃深蹲",
        "平板支撑",
    ]
    assert (
        squat["rest"] == 120 and len(squat["sets"]) == 3 and squat["target"] == "计划 3 组 × 8–10"
    )
    assert plank["timed"] and plank["sets"][0]["reps"] is None and plank["rest"] == 90


SQUAT_LAST = WorkoutLog(day=TODAY - timedelta(days=3), items=[LogItem(exercise="杠铃深蹲", done_sets=[
    SetDone(reps=10, weight_kg=60), SetDone(reps=10, weight_kg=60)])])  # fmt: skip


def test_plan_prefill_without_the_coach_is_last_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """§163 需求 6：管家没定下次目标，开练预填照上次的重量和次数（不按规则加重），组数照计划。"""
    c, _, _ = client(monkeypatch, plan=PLAN, logs=(SQUAT_LAST,))
    squat = c.post("/iron/api/live/start", json={"today_plan": True}).json()["live"]["items"][0]
    assert [(s["weight_kg"], s["reps"]) for s in squat["sets"]] == [(60, 10)] * 3  # 少做的组照上次最后一组
    assert squat["target"] == "上次 60×10、60×10" and squat["plan_kg"] == 60


def test_plan_prefill_uses_the_coach_target_while_it_holds(monkeypatch: pytest.MonkeyPatch) -> None:
    from ironm_agent import web_more
    from ironm_agent.progression import Decided, day_mark

    d = Decided(exercise="杠铃深蹲", sets=4, reps="8–10", weight_kg=62.5, why="上次轻松，加 2.5", after=SQUAT_LAST.day,
                mark=day_mark("杠铃深蹲", [SQUAT_LAST], SQUAT_LAST.day), plan="3×8–10")  # fmt: skip

    async def mine(_: str) -> dict[str, Any]:
        return {"杠铃深蹲": d}

    monkeypatch.setattr(web_more, "decided_targets", mine)
    c, book, _ = client(monkeypatch, plan=PLAN, logs=(SQUAT_LAST,))
    squat = c.post("/iron/api/live/start", json={"today_plan": True}).json()["live"]["items"][0]
    assert [(s["weight_kg"], s["reps"]) for s in squat["sets"]] == [(62.5, 8)] * 4  # 管家定的组数、重量
    assert squat["target"] == "目标 62.5 公斤 × 8–10 次 × 4 组"
    c.delete("/iron/api/live")
    newer = WorkoutLog(day=TODAY - timedelta(days=1), items=[LogItem(exercise="杠铃深蹲", done_sets=[
        SetDone(reps=9, weight_kg=60)] * 3)])  # fmt: skip
    asyncio.run(book.log("42", newer))  # 之后又练了一次：管家定的不再算数，照上次
    squat = c.post("/iron/api/live/start", json={"today_plan": True}).json()["live"]["items"][0]
    assert [(s["weight_kg"], s["reps"]) for s in squat["sets"]] == [(60, 9)] * 3


def test_unknown_move_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    c, _, _ = client(monkeypatch)
    assert c.post("/iron/api/live/start", json={"exercises": ["自创动作"]}).status_code == 422


def test_each_change_is_saved_and_changed_rest_is_remembered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c, _, lives = client(monkeypatch)
    live = c.post("/iron/api/live/start", json={"exercises": ["哑铃卧推"]}).json()["live"]
    item = live["items"][0]
    item["sets"][0] |= {"weight_kg": 22.5, "reps": 8}
    done(item, 0, seconds=35)  # 点了计时
    item["rest"] = 75
    saved = c.put("/iron/api/live", json={"id": live["id"], "items": live["items"]}).json()
    assert saved["live"]["items"][0]["sets"][0]["seconds"] == 35
    assert c.get("/iron/api/live").json()["live"]["items"][0]["sets"][0]["done"]  # 刷新后接着练
    assert asyncio.run(lives.rests("42")) == {"哑铃卧推": 75}
    c.delete("/iron/api/live")
    nxt = c.post("/iron/api/live/start", json={"exercises": ["哑铃卧推"]}).json()["live"]
    assert nxt["items"][0]["rest"] == 75  # 改过的下次照用
    stale = c.put("/iron/api/live", json={"id": "old", "items": []})
    assert stale.status_code == 409


def test_add_a_move_midway(monkeypatch: pytest.MonkeyPatch) -> None:
    c, _, _ = client(monkeypatch)
    c.post("/iron/api/live/start", json={})
    got = c.post("/iron/api/live/items", json={"exercise": "平板支撑"}).json()["live"]
    assert [x["exercise"] for x in got["items"]] == ["平板支撑"] and got["items"][0]["timed"]


def test_finish_saves_only_done_sets_with_time(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    c, book, lives = client(monkeypatch)
    live = c.post("/iron/api/live/start", json={"exercises": ["哑铃卧推", "平板支撑"]}).json()[
        "live"
    ]
    bench, plank = live["items"]
    bench["sets"][0] |= {"weight_kg": 20, "reps": 10}
    done(bench, 0)  # 没计时
    bench["sets"][1] |= {"weight_kg": 20, "reps": 8}
    done(bench, 1, seconds=40)
    done(plank, 0, seconds=45)
    c.put("/iron/api/live", json={"id": live["id"], "items": live["items"]})
    stored = asyncio.run(lives.get("42"))
    assert stored is not None
    asyncio.run(
        lives.save(
            "42", stored.model_copy(update={"started": datetime.now() - timedelta(minutes=50)})
        )
    )
    with caplog.at_level(logging.DEBUG):
        got = c.post("/iron/api/live/finish", json={"rpe": 7}).json()
    assert got["summary"] == {
        "minutes": 50,
        "exercises": 2,
        "sets": 3,
        "volume": 360,
    }  # 20×10 + 20×8，计时类不算
    log = got["workout"]
    assert log["minutes"] == 50 and log["rpe"] == 7 and len(log["items"]) == 2
    first = log["items"][0]["done_sets"]
    assert first[0]["seconds"] is None and first[1]["seconds"] == 40 and first[0]["at"]
    assert "平板支撑 45 秒" in log["line"]
    assert (
        len(asyncio.run(book.workouts("42", TODAY))) == 1 and asyncio.run(lives.get("42")) is None
    )
    assert "哑铃卧推" not in caplog.text


def test_idle_for_six_hours_finishes_with_done_sets_only(monkeypatch: pytest.MonkeyPatch) -> None:
    c, book, lives = client(monkeypatch)
    live = c.post("/iron/api/live/start", json={"exercises": ["哑铃卧推"]}).json()["live"]
    done(live["items"][0], 0, weight_kg=20, reps=10)
    c.put("/iron/api/live", json={"id": live["id"], "items": live["items"]})
    stored = asyncio.run(lives.get("42"))
    assert stored is not None
    old = datetime.now() - IDLE - timedelta(minutes=5)
    asyncio.run(
        lives.save(
            "42", stored.model_copy(update={"updated": old, "started": old - timedelta(minutes=40)})
        )
    )
    got = c.get("/iron/api/live").json()
    assert got["live"] is None and got["expired"]["minutes"] == 40
    assert (
        len(got["expired"]["items"][0]["done_sets"]) == 1
        and len(asyncio.run(book.workouts("42", TODAY - timedelta(days=1)))) == 1
    )


def test_discard_leaves_no_record(monkeypatch: pytest.MonkeyPatch) -> None:
    c, book, lives = client(monkeypatch)
    live = c.post("/iron/api/live/start", json={"exercises": ["哑铃卧推"]}).json()["live"]
    done(live["items"][0], 0, weight_kg=20, reps=10)
    c.put("/iron/api/live", json={"id": live["id"], "items": live["items"]})
    c.delete("/iron/api/live")
    assert asyncio.run(lives.get("42")) is None and asyncio.run(book.workouts("42", TODAY)) == []


def test_nothing_done_saves_nothing() -> None:
    now = datetime.now()
    live = Live(
        id="x", started=now, updated=now, items=[LiveItem(exercise="哑铃卧推", sets=[LiveSet()])]
    )
    assert to_log(live, TODAY, now) is None


def test_db_version_encrypts_the_live_session(monkeypatch: pytest.MonkeyPatch) -> None:
    from ironm_agent import live as mod

    seen: list[tuple[str, dict[str, Any]]] = []

    async def fake(sql: str, params: dict[str, Any], log_sql: bool = True) -> list[dict[str, Any]]:
        seen.append((sql, params))
        return []

    monkeypatch.setattr("mirobody.utils.db.execute_query", fake)
    now = datetime.now()
    asyncio.run(
        mod.PgLive().save(
            "42", Live(id="x", started=now, updated=now, items=[LiveItem(exercise="哑铃卧推")])
        )
    )
    sql = next(s for s, _ in seen if "INSERT" in s)
    assert "encrypt_content(:c)" in sql and "哑铃卧推" not in sql
