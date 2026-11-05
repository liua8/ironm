"""训练中实时调整（spec [2026-10-23] §90）：模型决定后面怎么练，代码只改没完成的组、守安全底线。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from ironm_agent import spoken
from ironm_agent.live import Live, LiveItem, LiveSet
from ironm_agent.live_adjust import FAILED, apply, current, session_lines
from ironm_agent.llm import Reply
from tests.fakes import FakeLLM, jsonr
from tests.test_live import PLAN, client, done

NOW = datetime.now()


def squat(*done_sets: bool) -> LiveItem:
    return LiveItem(
        exercise="杠铃深蹲", sets=[LiveSet(weight_kg=80, reps=8, done=d) for d in done_sets]
    )


def session(*items: LiveItem) -> Live:
    return Live(id="x", started=NOW, updated=NOW, items=list(items))


def weights(live: Live, i: int = 0) -> list[tuple[float | None, bool]]:
    return [(s.weight_kg, s.done) for s in live.items[i].sets]


def test_only_unfinished_sets_change_and_increases_are_capped() -> None:
    live = session(squat(True, False, False))
    assert current(live) == 0
    new, kinds, dropped = apply(live, [{"kind": "all", "item": 1, "weight_kg": 70}], hurt=False)
    assert weights(new) == [(80, True), (70, False), (70, False)] and kinds == ["all"]  # 做完的不动
    new, _, _ = apply(
        live, [{"kind": "set", "item": 1, "set": 2, "weight_kg": 100, "reps": 6}], hurt=False
    )
    assert (
        new.items[0].sets[1].weight_kg == 85 and new.items[0].sets[1].reps == 6
    )  # 下肢一次最多加 5 公斤
    new, kinds, dropped = apply(live, [
        {"kind": "set", "item": 1, "set": 1, "weight_kg": 60},  # 做完的那组：不改
        {"kind": "all", "item": 9, "weight_kg": 60},  # 没有这个动作
        {"kind": "all", "item": 1, "weight_kg": 900},  # 越界
        {"kind": "fly"},
    ], hurt=False)  # fmt: skip
    assert weights(new) == weights(live) and not kinds and dropped == 4
    assert live.items[0].sets[1].weight_kg == 80  # 原来的没被改动


def test_unset_weight_is_capped_against_what_was_done() -> None:
    live = session(
        LiveItem(
            exercise="杠铃深蹲", sets=[LiveSet(weight_kg=80, reps=8, done=True), LiveSet(reps=8)]
        )
    )
    new, _, _ = apply(live, [{"kind": "all", "item": 1, "weight_kg": 100}], hurt=False)
    assert new.items[0].sets[1].weight_kg == 85
    new, _, _ = apply(live, [{"kind": "all", "item": 1, "weight_kg": 100}], hurt=True)
    assert new.items[0].sets[1].weight_kg == 80


def test_bench_60_that_felt_light_goes_up_one_step_not_to_65() -> None:
    """项目负责人 10-30：卧推 60 公斤说轻松，被直接加到 65，不合常理（§90 需求 6）。"""
    bench = LiveItem(exercise="杠铃卧推", target="计划 3 组 × 8–12",
                     sets=[LiveSet(weight_kg=60, reps=5, done=True), LiveSet(weight_kg=60, reps=5)])  # fmt: skip
    new, _, _ = apply(session(bench), [{"kind": "all", "item": 1, "weight_kg": 65}], hurt=False)
    assert new.items[0].sets[1].weight_kg == 62.5  # 上肢一次最多 2.5 公斤
    assert "（目标：计划 3 组 × 8–12）" in session_lines(session(bench))[0]
    from ironm_agent.live_adjust import _PROMPT

    assert "先加次数" in _PROMPT and "不超过一成" not in _PROMPT and "还能再做几个" in _PROMPT


def test_pain_means_no_heavier_and_no_extra_sets() -> None:
    live = session(squat(True, False, False))
    new, _, dropped = apply(live, [{"kind": "all", "item": 1, "weight_kg": 85},
                                       {"kind": "add_sets", "item": 1, "count": 1}], hurt=True)  # fmt: skip
    assert weights(new) == weights(live) and dropped == 1  # 不加重（照原重量）、不加组
    new, _kinds, _ = apply(live, [{"kind": "all", "item": 1, "weight_kg": 60}], hurt=True)
    assert weights(new)[1] == (60, False)  # 减重照样可以


def test_add_drop_skip_and_swap() -> None:
    live = session(
        squat(True, False, False),
        LiveItem(exercise="哑铃卧推", sets=[LiveSet(weight_kg=20, reps=10)]),
    )
    new, kinds, _ = apply(live, [{"kind": "add_sets", "item": 1, "count": 2}], hurt=False)
    assert len(new.items[0].sets) == 5 and new.items[0].sets[-1].weight_kg == 80
    new, _, _ = apply(live, [{"kind": "drop_sets", "item": 1, "count": 1}], hurt=False)
    assert weights(new) == [(80, True), (80, False)]
    new, _, _ = apply(live, [{"kind": "skip", "item": 1}, {"kind": "skip", "item": 2}], hurt=False)
    assert [x.exercise for x in new.items] == ["杠铃深蹲"] and weights(new) == [
        (80, True)
    ]  # 一组没做的拿掉
    new, kinds, _ = apply(live, [{"kind": "swap", "item": 1, "to": "高脚杯深蹲"},
                                 {"kind": "all", "item": 2, "weight_kg": 18}], hurt=False)  # fmt: skip
    assert [x.exercise for x in new.items] == ["杠铃深蹲", "高脚杯深蹲", "哑铃卧推"]
    assert weights(new) == [(80, True)] and len(new.items[1].sets) == 2  # 后面两组换成新动作
    assert new.items[2].sets[0].weight_kg == 18  # 动作号仍按原来的算
    _, kinds, dropped = apply(live, [{"kind": "swap", "item": 1, "to": "不存在的动作"}], hurt=False)
    assert not kinds and dropped == 1


def start(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any, dict[str, Any], Any]:
    from ironm_agent import web_live, web_more
    from ironm_agent.triggers import PainBook

    c, _, lives = client(monkeypatch, plan=PLAN)
    pains = PainBook()
    c.app.dependency_overrides[web_more.pain_store] = lambda: pains  # type: ignore[attr-defined]

    async def no_coach(_: str) -> str:
        return "今天的训练按约7成练（这周练多了）"

    monkeypatch.setattr(web_live, "coach_today", no_coach)
    live = c.post("/iron/api/live/start", json={"today_plan": True}).json()["live"]
    for s in live["items"][0]["sets"]:
        s["weight_kg"] = 80
    done(live["items"][0], 0)
    c.put("/iron/api/live", json={"id": live["id"], "items": live["items"]})
    return c, lives, live, pains


def test_tired_mid_workout_changes_the_rest_of_the_sets(monkeypatch: pytest.MonkeyPatch) -> None:
    c, lives, live, _ = start(monkeypatch)
    seen: list[str] = []

    def answer(stage: Any, messages: Any, tools: Any) -> Reply:
        seen.append(str(messages[-1]["content"]))
        return jsonr({"say": "后面两组减到 60 公斤，每组 6 个，别做到力竭。", "end": False,
                      "changes": [{"kind": "all", "item": 1, "weight_kg": 60, "reps": 6}]})  # fmt: skip

    monkeypatch.setattr(spoken, "default_llm", lambda: FakeLLM(answer))
    r = c.post("/iron/api/live/adjust", json={"id": live["id"], "said": "很累"}).json()
    assert r["say"].startswith("后面两组减到 60 公斤") and r["changed"] == 1 and not r["urgent"]
    sets = r["live"]["items"][0]["sets"]
    assert sets[0]["done"] and [(s["weight_kg"], s["reps"]) for s in sets[1:]] == [(60, 6), (60, 6)]
    assert (
        "动作1 杠铃深蹲（目标：计划 3 组 × 8–10）：做完 第1组" in seen[0]
    )  # 带目标次数（§90 需求 6）
    assert "他说（关于动作1 杠铃深蹲）：很累" in seen[0]
    assert "管家今天的调整：今天的训练按约7成练" in seen[0]
    import asyncio

    saved = asyncio.run(lives.get("42"))
    assert saved.items[0].sets[1].weight_kg == 60  # 存下了，刷新回来还在


def test_emergency_and_model_failure_change_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    c, _, live, _ = start(monkeypatch)
    before = c.get("/iron/api/live").json()["live"]["items"]
    r = c.post("/iron/api/live/adjust", json={"id": live["id"], "said": "很累"}).json()
    assert r["say"] == FAILED and r["live"]["items"] == before  # 默认模型不可用：不改
    monkeypatch.setattr(spoken, "default_llm",
                        lambda: FakeLLM(lambda *_: Reply("马上停下来坐着，现在就打 120。")))  # fmt: skip
    r = c.post(
        "/iron/api/live/adjust", json={"id": live["id"], "said": "胸口突然很痛，喘不上气"}
    ).json()
    assert r["urgent"] and r["end"] and "120" in r["say"] and r["live"]["items"] == before
    assert c.post("/iron/api/live/adjust", json={"id": "old", "said": "很累"}).status_code == 409


def test_pain_is_recorded_and_blocks_heavier(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    from datetime import date

    c, _, live, pains = start(monkeypatch)
    reply = {"say": "先停深蹲，换成箱式深蹲，蹲到不疼的高度。",
             "changes": [{"kind": "all", "item": 1, "weight_kg": 85}]}  # fmt: skip
    monkeypatch.setattr(spoken, "default_llm", lambda: FakeLLM(lambda *_: jsonr(reply)))
    from ironm_agent import web_live

    read: list[tuple[str, str]] = []
    monkeypatch.setattr(
        web_live, "body_later", lambda uid, text, day, where: read.append((text, where))
    )
    r = c.post("/iron/api/live/adjust", json={"id": live["id"], "said": "膝盖有点疼"}).json()
    assert [s["weight_kg"] for s in r["live"]["items"][0]["sets"][1:]] == [
        80,
        80,
    ]  # 说疼：不加重（安全护栏）
    assert read == [("膝盖有点疼", "训练中")]  # 疼在哪由管家读出来再记（§163），不按关键词记
    assert not asyncio.run(pains.since("42", date.today()))
