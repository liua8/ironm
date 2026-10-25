"""数据页（spec [2026-10-23] §26 需求 3、4）：补读的指标、单位统一、自己记一条 / 改 / 删。不连数据库。"""

import asyncio
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ironm_agent.healthdata import read_all
from ironm_agent.metrics import Profile, Readings, compute_all
from ironm_agent.readings import KINDS, OutOfRange, ReadingBook, check
from tests.test_healthdata import FakeHealth, days, no_raw

TODAY = date(2026, 10, 25)


def pts(values: list[float], end: date = TODAY) -> tuple[tuple[date, float], ...]:
    return tuple((end - timedelta(days=len(values) - 1 - i), v) for i, v in enumerate(values))


def test_new_metrics_only_when_there_is_data_and_old_ids_stay() -> None:
    p = Profile(
        height_cm=178, birth=date(1994, 5, 1), sex="male", goal="muscle", activity="moderate"
    )
    base = [m.key for m in compute_all(Readings(weight=pts([70.0])), p, TODAY)]
    r = Readings(weight=pts([70.0]), body_fat=pts([19.0, 18.5]), waist=pts([92.0]),
                 active_kcal=pts([400, 500, 450]), exercise_min=pts([30, 40, 0, 50, 0, 20, 30]),
                 lean_mass=pts([57.0]), vo2max=pts([45.0]))  # fmt: skip
    full = compute_all(r, p, TODAY)
    keys = [m.key for m in full]
    assert keys[: len(base)] == base  # 已有指标的顺序（C 编号）不变
    assert keys[len(base) :] == [
        "body_fat",
        "waist",
        "active_kcal",
        "exercise_min",
        "lean_mass",
        "vo2max",
    ]
    by = {m.key: m for m in full}
    assert by["body_fat"].value == 18.5 and "近 4 周-0.5" in by["body_fat"].text
    assert (
        by["waist"].tone == "attention"
        and "90 厘米" in by["waist"].text
        and "WS/T 428" in by["waist"].source
    )
    assert by["active_kcal"].value == 450
    assert (
        by["exercise_min"].value == 170
        and by["exercise_min"].tone == "good"
        and by["exercise_min"].ref == "K01"
    )
    female = {
        m.key: m for m in compute_all(Readings(waist=pts([84.0])), Profile(sex="female"), TODAY)
    }
    assert female["waist"].tone == "good"


def test_waist_in_meters_and_body_fat_as_fraction_are_unified() -> None:
    first = TODAY - timedelta(days=1)
    svc = FakeHealth({
        "waistCircumferences": days(first, [0.82, 0.81], "m"),
        "bodyFatPercentages": days(first, [0.185, 18.0], "%"),
        "activeCalories": days(first, [420.0, 380.0], "kcal"),
    })  # fmt: skip
    r = asyncio.run(read_all(svc, "42", TODAY, no_raw))
    assert [round(v, 1) for _, v in r.waist] == [82.0, 81.0]  # 米换成厘米
    assert [round(v, 1) for _, v in r.body_fat] == [18.5, 18.0]  # 小数换成百分数
    assert [v for _, v in r.active_kcal] == [420.0, 380.0]


def test_range_check() -> None:
    assert check("weight", 70).title == "体重"
    with pytest.raises(OutOfRange, match="20–300 公斤"):
        check("weight", 700)
    assert set(KINDS) >= {
        "weight",
        "body_fat",
        "waist",
        "resting_hr",
        "sleep",
        "systolic",
        "diastolic",
    }


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch, coach_in_memory: list[tuple[str, str]]
) -> tuple[TestClient, ReadingBook]:
    from mirobody.server.auth import verify_token

    from ironm_agent import web, web_more

    book = ReadingBook()
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: "42"
    app.dependency_overrides[web_more.reading_store] = lambda: book
    return TestClient(app), book


def test_add_fix_delete(
    client: tuple[TestClient, ReadingBook], coach_in_memory: list[tuple[str, str]]
) -> None:
    c, book = client
    r = c.post("/iron/api/readings", json={"kind": "weight", "value": 70.2})
    assert r.status_code == 200 and r.json()["rows"][0]["value"] == 70.2
    assert ("42", "记数据") in coach_in_memory  # 记了数：管家重新评估
    assert c.post("/iron/api/readings", json={"kind": "weight", "value": 700}).status_code == 422
    assert (
        c.post("/iron/api/readings", json={"kind": "bmi", "value": 22}).status_code == 422
    )  # 计算类不能记
    future = (date.today() + timedelta(days=1)).isoformat()
    assert (
        c.post(
            "/iron/api/readings", json={"kind": "weight", "value": 70, "day": future}
        ).status_code
        == 422
    )
    row_id = r.json()["rows"][0]["id"]
    fixed = c.post(f"/iron/api/readings/weight/{row_id}", json={"value": 69.8}).json()["rows"]
    assert [x["value"] for x in fixed] == [69.8]
    assert len(book.rows["42"]) == 2 and not book.rows["42"][0]["active"]  # 原记录保留
    assert c.delete(f"/iron/api/readings/weight/{fixed[0]['id']}").json()["rows"] == []
    assert c.delete(f"/iron/api/readings/weight/{fixed[0]['id']}").status_code == 404
    listing = c.get("/iron/api/readings?kind=waist").json()
    assert listing["title"] == "腰围" and listing["unit"] == "厘米" and listing["rows"] == []
