"""训练流程理顺、有氧按时长记（spec [2026-10-23] §130）。"""

from __future__ import annotations

from typing import Any

import pytest

from ironm_agent.live import LiveItem
from ironm_agent.training import LogItem, Plan, WorkoutLog
from tests.test_live import PLAN, TODAY, client, done

RIDE = "骑行（动感单车）"
CARDIO = Plan.model_validate({"title": "全身", "days_per_week": 1, "sessions": [{
    "day": TODAY.isoweekday(), "name": "全身 A", "minutes": 50,
    "items": [{"exercise": "杠铃深蹲", "sets": 3, "reps": "8–10"}, {"exercise": RIDE, "sets": 1, "reps": "20–30 分钟"}],
}]})  # fmt: skip


def names(live: dict[str, Any]) -> list[str]:
    return [x["exercise"] for x in live["items"]]


def start(c: Any, **body: Any) -> dict[str, Any]:
    return c.post("/iron/api/live/start", json=body).json()["live"]  # type: ignore[no-any-return]


def test_starting_from_a_move_brings_today_plan_after_it(monkeypatch: pytest.MonkeyPatch) -> None:
    c, _, _ = client(monkeypatch, plan=PLAN)
    got = start(c, exercises=["平板支撑"])
    assert (
        names(got) == ["平板支撑", "杠铃深蹲"] and got["session"] == "全身 A"
    )  # 点的排第一，不重复


def test_free_start_brings_today_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    c, _, _ = client(monkeypatch, plan=PLAN)
    assert names(start(c)) == ["杠铃深蹲", "平板支撑"]


def test_no_plan_when_today_already_trained(monkeypatch: pytest.MonkeyPatch) -> None:
    trained = WorkoutLog(
        day=TODAY, session="全身 A", items=[LogItem(exercise="杠铃深蹲", sets=3, reps="8")]
    )
    c, _, _ = client(monkeypatch, plan=PLAN, logs=(trained,))
    got = start(c, exercises=["哑铃弯举"])
    assert names(got) == ["哑铃弯举"] and got["session"] == ""


def test_move_is_added_to_a_running_session(monkeypatch: pytest.MonkeyPatch) -> None:
    c, _, _ = client(monkeypatch, plan=PLAN)
    first = start(c, today_plan=True)
    got = start(c, exercises=["哑铃弯举"])
    assert got["id"] == first["id"] and names(got) == ["杠铃深蹲", "平板支撑", "哑铃弯举"]
    assert names(start(c, exercises=["杠铃深蹲"])) == names(got)  # 已经在里面的不重复


def test_cardio_is_one_timed_bout_prefilled_from_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    c, _, _ = client(monkeypatch, plan=CARDIO)
    got = start(c, today_plan=True)
    ride = got["items"][1]
    assert ride["cardio"] and ride["timed"] and len(ride["sets"]) == 1
    assert (
        ride["sets"][0]["seconds"] == 20 * 60
        and ride["sets"][0]["weight_kg"] is None
        and ride["sets"][0]["reps"] is None
    )
    assert not got["items"][0]["cardio"]
    done(ride, 0, seconds=25 * 60)
    assert c.put("/iron/api/live", json={"id": got["id"], "items": got["items"]}).status_code == 200


def test_old_sessions_without_the_field_still_load() -> None:
    old = LiveItem.model_validate({"exercise": "杠铃深蹲", "sets": []})
    assert old.cardio is False


def test_page_rules() -> None:
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "ironm_agent" / "web" / "app.js").read_text()
    live = js[js.index("async function livePage(view)") :]
    assert "it.cardio" in live and '"分钟"' in live and '"再加一段"' in live  # 有氧一段一行填分钟
    assert "s.seconds = m ? Math.round(m * 60) : null" in live  # 存秒
    assert 'liveEntry({ free: true }, "自由训练")' in js  # §133：图鉴的入口改回自由训练（空的开始）
    assert 'partOf(lib ?? cache.exercises, it.exercise) === "有氧"' in js  # 首页、计划页有氧写时长
    render = js[js.index("async function render()") :]
    assert "}, 250);" in render and "samePage" in render  # 读得慢才出骨架；同页重画不跳回顶部
