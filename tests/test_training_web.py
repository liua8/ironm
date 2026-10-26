"""计划与记录的接口（spec [2026-10-23] §9、§10）：预览确认 / 取消 / 撤销、只能动自己的、首页简报与复盘。"""

import asyncio
from datetime import date, timedelta
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ironm_agent.casefile import Snapshot
from ironm_agent.memory_store import MemoryBook
from ironm_agent.metrics import Profile, Readings, compute_all
from ironm_agent.training import Plan, TrainingBook, WorkoutLog, log_content, plan_content

PLAN = Plan.model_validate(
    {
        "title": "三分化",
        "days_per_week": 3,
        "sessions": [
            {"day": d, "name": n, "items": [{"exercise": "深蹲", "sets": 3, "reps": "10"}]}
            for d, n in ((1, "下肢"), (3, "上肢推"), (5, "上肢拉"))
        ],
    }
)


def client(user: str = "42", monkeypatch: Any = None) -> tuple[TestClient, TrainingBook]:
    from mirobody.server.auth import verify_token

    from ironm_agent import web

    book = TrainingBook()
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: user
    app.dependency_overrides[web.training_store] = lambda: book
    app.dependency_overrides[web.memory_store] = lambda: MemoryBook()
    return TestClient(app), book


def test_confirm_cancel_undo_through_the_api() -> None:
    c, book = client()
    d = asyncio.run(book.add_draft("42", "plan", plan_content(PLAN, "新排的")))
    got = c.get(f"/iron/api/drafts/{d.id}").json()["draft"]
    assert (
        got["state"] == "pending"
        and got["changes"] == "新排的"
        and got["plan"]["title"] == "三分化"
    )
    assert c.get("/iron/api/training").json()["plan"] is None  # 确认前没有计划
    assert c.post(f"/iron/api/drafts/{d.id}/confirm").json()["draft"]["state"] == "confirmed"
    assert c.post(f"/iron/api/drafts/{d.id}/confirm").status_code == 200  # 点两次不重复写入
    assert c.get("/iron/api/training").json()["plan"]["title"] == "三分化"
    assert c.post(f"/iron/api/drafts/{d.id}/undo").json()["draft"]["state"] == "undone"
    assert c.get("/iron/api/training").json()["plan"] is None
    assert c.post(f"/iron/api/drafts/{d.id}/confirm").status_code == 409

    log = asyncio.run(book.add_draft("42", "log", log_content(WorkoutLog(day=date.today(), rpe=7))))
    assert c.post(f"/iron/api/drafts/{log.id}/cancel").json()["draft"]["state"] == "cancelled"
    assert c.get("/iron/api/training").json()["workouts"] == []


def test_someone_else_cannot_see_or_confirm() -> None:
    c, book = client(user="7")
    d = asyncio.run(book.add_draft("42", "plan", plan_content(PLAN)))
    assert c.get(f"/iron/api/drafts/{d.id}").status_code == 404
    assert c.post(f"/iron/api/drafts/{d.id}/confirm").status_code == 404
    assert asyncio.run(book.plan("42")) is None


def test_quick_log_from_home_and_delete() -> None:
    c, _ = client()
    w = c.post("/iron/api/workouts", json={"session": "下肢", "rpe": 7, "note": "膝盖没疼"}).json()[
        "workout"
    ]
    assert w["rpe"] == 7 and "下肢" in w["line"]
    assert c.post("/iron/api/workouts", json={"rpe": 11}).status_code == 422
    assert [x["id"] for x in c.get("/iron/api/training").json()["workouts"]] == [w["id"]]
    assert c.delete(f"/iron/api/workouts/{w['id']}").status_code == 200
    assert c.delete(f"/iron/api/workouts/{w['id']}").status_code == 404


def test_brief_and_weekly_review_use_rules_only(monkeypatch: Any) -> None:
    from ironm_agent import web

    today = date.today()
    nights = tuple((today - timedelta(days=i), 6.2) for i in range(7))
    profile = Profile(
        height_cm=170, birth=date(1995, 1, 1), sex="female", goal="fat_loss", activity="light"
    )
    weights = tuple((today - timedelta(days=i), 70.0 + (i % 2) * 0.2) for i in range(30))
    readings = Readings(weight=weights, sleep_hours=nights)

    async def snap(_: str) -> Snapshot:
        return Snapshot(profile, readings, tuple(compute_all(readings, profile, today)), today)

    monkeypatch.setattr(web, "snapshot_for", snap)
    c, book = client()
    book.seed("42", PLAN, [])
    data = c.get("/iron/api/brief").json()
    t = data["today"]["training"]
    session = PLAN.session_on(today)
    assert t["kind"] == ("session" if session else "rest")
    assert data["today"]["nutrition"]["kcal"] is not None
    tips = "".join(data["week"]["tips"])
    assert "平均只睡 6.2 小时" in tips and "少吃约 200 千卡" in tips
    if data["week"]["due"] >= 2:
        assert "不到一半" in tips  # 这周一次都没练


def test_brief_carries_the_safety_alert_only_when_there_is_a_risk(monkeypatch: Any) -> None:
    """安全提醒放首页（spec [2026-10-23] §42）。"""
    from ironm_agent import web

    today = date.today()
    profile = Profile(
        height_cm=170, birth=date(1995, 1, 1), sex="male", goal="muscle", activity="light"
    )

    def with_bp(systolic: float, diastolic: float) -> Any:
        readings = Readings(
            systolic=((today - timedelta(days=2), systolic),),
            diastolic=((today - timedelta(days=2), diastolic),),
        )

        async def snap(_: str) -> Snapshot:
            return Snapshot(profile, readings, tuple(compute_all(readings, profile, today)), today)

        return snap

    monkeypatch.setattr(web, "snapshot_for", with_bp(164, 102))
    c, _ = client()
    alerts = c.get("/iron/api/brief").json()["alerts"]
    assert (
        [a["key"] for a in alerts] == ["bp_high"]
        and "164/102" in alerts[0]["text"]
        and alerts[0]["title"]
    )
    monkeypatch.setattr(web, "snapshot_for", with_bp(118, 76))
    assert c.get("/iron/api/brief").json()["alerts"] == []
