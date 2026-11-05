"""开练自动带上今天的计划（spec [2026-10-23] §123）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ironm_agent.training import Plan
from tests.test_live import PLAN, TODAY, client, done

ODD = Plan.model_validate({"title": "全身", "days_per_week": 1, "sessions": [{
    "day": TODAY.isoweekday(), "name": "全身 A", "minutes": 45,
    "items": [{"exercise": "杠铃深蹲", "sets": 3, "reps": "8–10"},
              {"exercise": "史密斯机分腿蹲", "sets": 3, "reps": "10"}],
}]})  # fmt: skip


def save(c: Any, live: dict[str, Any]) -> Any:
    return c.put("/iron/api/live", json={"id": live["id"], "items": live["items"]})


def names(live: dict[str, Any]) -> list[str]:
    return [x["exercise"] for x in live["items"]]


def test_free_session_then_plan_adds_the_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    c, _, _ = client(monkeypatch, plan=PLAN)
    free = c.post("/iron/api/live/start", json={}).json()["live"]
    assert names(free) == ["杠铃深蹲", "平板支撑"]  # §130：从哪开始都带上今天的计划
    got = c.post("/iron/api/live/start", json={"today_plan": True}).json()["live"]
    assert names(got) == ["杠铃深蹲", "平板支撑"] and got["session"] == "全身 A"


def test_started_from_a_move_keeps_its_sets_and_appends_the_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c, _, _ = client(monkeypatch, plan=PLAN)
    live = c.post("/iron/api/live/start", json={"exercises": ["平板支撑"]}).json()["live"]
    done(live["items"][0], 0, seconds=40)
    save(c, live)
    got = c.post("/iron/api/live/start", json={"today_plan": True}).json()["live"]
    assert names(got) == ["平板支撑", "杠铃深蹲"]  # 不重复，接在后面
    assert got["items"][0]["sets"][0]["done"] and got["items"][0]["sets"][0]["seconds"] == 40


def test_removed_move_does_not_come_back(monkeypatch: pytest.MonkeyPatch) -> None:
    c, _, _ = client(monkeypatch, plan=PLAN)
    live = c.post("/iron/api/live/start", json={"today_plan": True}).json()["live"]
    live["items"] = live["items"][:1]
    save(c, live)
    got = c.post("/iron/api/live/start", json={"today_plan": True}).json()["live"]
    assert names(got) == ["杠铃深蹲"]


def test_plan_moves_outside_the_library_are_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    c, _, _ = client(monkeypatch, plan=ODD)
    got = c.post("/iron/api/live/start", json={"today_plan": True}).json()["live"]
    odd = got["items"][1]
    assert names(got) == ["杠铃深蹲", "史密斯机分腿蹲"]
    assert not odd["timed"] and len(odd["sets"]) == 3 and odd["target"] == "计划 3 组 × 10"
    done(got["items"][1], 0, weight_kg=40, reps=10)
    assert save(c, got).status_code == 200  # 带进来的动作能照常记
    r = c.post("/iron/api/live/items", json={"exercise": "史密斯机分腿蹲"})
    assert r.status_code == 422  # 自己手动加仍只能加库里的


def test_home_continue_card_starts_from_plan() -> None:
    js = (Path(__file__).resolve().parents[1] / "ironm_agent" / "web" / "app.js").read_text()
    home = js[js.index("async function home(view)") : js.index("const partOf")]
    assert "liveNow ? liveEntry({ today_plan: true }) : null" in home
