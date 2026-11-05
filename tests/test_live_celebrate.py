"""完成反馈（spec [2026-10-23] §92）：开始时带上以前最好的一组，练完返回破了的纪录和本周进度。"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from ironm_agent.live import best_e1rm, records
from ironm_agent.training import LogItem, SetDone, WorkoutLog
from tests.test_live import PLAN, TODAY, client, done

BEFORE = WorkoutLog(day=TODAY - timedelta(days=10), items=[
    LogItem(exercise="杠铃卧推", done_sets=[SetDone(reps=8, weight_kg=60), SetDone(reps=5, weight_kg=62.5)]),
    LogItem(exercise="平板支撑", done_sets=[SetDone(reps=0, seconds=60)]),
])  # fmt: skip


def test_best_and_records_use_the_estimated_max() -> None:
    assert best_e1rm("杠铃卧推", [BEFORE]) == 76.0  # 60×8 → 76，比 62.5×5（72.9）高
    assert best_e1rm("平板支撑", [BEFORE]) is None and best_e1rm("深蹲", [BEFORE]) is None
    now = WorkoutLog(day=TODAY, items=[
        LogItem(exercise="杠铃卧推", done_sets=[SetDone(reps=8, weight_kg=62.5), SetDone(reps=6, weight_kg=62.5)]),
        LogItem(exercise="哑铃卧推", done_sets=[SetDone(reps=10, weight_kg=20)]),  # 以前没做过：不算
    ])  # fmt: skip
    [pr] = records(now, [BEFORE])
    assert pr == {
        "exercise": "杠铃卧推",
        "weight_kg": 62.5,
        "reps": 8,
        "e1rm": 79.2,
        "before": 76.0,
    }
    assert not records(BEFORE, [BEFORE])  # 追平不算


def test_finish_returns_records_and_the_week(monkeypatch: pytest.MonkeyPatch) -> None:
    c, _, _ = client(monkeypatch, plan=PLAN, logs=(BEFORE,))
    live = c.post("/iron/api/live/start", json={"exercises": ["杠铃卧推"]}).json()["live"]
    item = live["items"][0]  # §130：从动作开始也带上今天的计划，点的那个排第一
    assert item["exercise"] == "杠铃卧推"
    assert item["best"] == 76.0  # 开始时带上以前最好的一组
    item["sets"][0] |= {"weight_kg": 62.5, "reps": 8}
    done(item, 0)
    c.put("/iron/api/live", json={"id": live["id"], "items": live["items"]})
    got: dict[str, Any] = c.post("/iron/api/live/finish", json={"rpe": 8}).json()["workout"][
        "celebrate"
    ]
    assert [p["exercise"] for p in got["prs"]] == ["杠铃卧推"]
    assert got["week"] == {
        "before": 0,
        "done": 1,
        "planned": 1,
        "reached_now": True,
    }  # 这一练刚好达成本周目标
