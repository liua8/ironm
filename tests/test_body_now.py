"""身体情况跨表合一（spec [2026-10-23] §158）：同一处身体以最近的说法为准。不连数据库、不调用模型。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

import pytest

from ironm_agent.body_now import fresh, healed_on, sore
from ironm_agent.memory_extract import validate
from ironm_agent.memory_layers import daily_asks
from ironm_agent.memory_store import Change, MemoryBook
from ironm_agent.triggers import PainBook
from tests.test_memory_layers import TODAY, at, item

KNEE = {"parts": ["joint.knee"], "side": "左"}


def knee(status: str, days_ago: int, i: str = "k") -> Any:
    x = item(i, "injury", "左膝疼" if status != "resolved" else "左膝好了", TODAY - timedelta(days=days_ago),
             status=status)  # fmt: skip
    return replace(x, data=dict(KNEE), key="injury:joint.knee:左")


def test_pain_on_or_before_the_healed_day_no_longer_counts() -> None:
    healed = knee("resolved", 2)
    pains = [("joint.knee", TODAY - timedelta(days=5)), ("joint.knee", TODAY - timedelta(days=2)),
             ("joint.knee", TODAY - timedelta(days=1)), ("joint.shoulder", TODAY - timedelta(days=5))]  # fmt: skip
    assert healed_on([healed]) == {"joint.knee": TODAY - timedelta(days=2)}
    assert fresh(pains, [healed]) == [pains[2], pains[3]]
    assert sore(pains, [healed], TODAY) == ["joint.knee"]  # 好了以后又说疼的，最近 3 天
    assert sore([("joint.knee", TODAY - timedelta(days=3))], [], TODAY) == []


def test_still_hurting_somewhere_on_that_joint_means_not_healed() -> None:
    other = replace(knee("active", 1, "r"), data={"parts": ["joint.knee"], "side": "右"},
                    key="injury:joint.knee:右")  # fmt: skip
    assert healed_on([knee("resolved", 2), other]) == {}
    old_heal = knee("resolved", 9)
    again = knee("active", 1, "a")  # 好了以后又记成在疼：最近的为准
    assert healed_on([old_heal, again]) == {}


def test_home_reminders_drop_knee_pain_from_before_he_said_it_healed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from mirobody.server.auth import verify_token

    from ironm_agent import web, web_more
    from ironm_agent.training import TrainingBook, plan_content
    from tests.test_adjust import THREE

    real = date.today()
    pain, memory, book = PainBook(), MemoryBook(), TrainingBook()
    d = asyncio.run(book.add_draft("42", "plan", plan_content(THREE)))
    asyncio.run(book.confirm("42", d.id))
    pain.rows["42"] = [
        ("joint.knee", real - timedelta(days=4)),
        ("joint.knee", real - timedelta(days=2)),
    ]
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: "42"
    for dep in (web_more.training_store, web.training_store):
        app.dependency_overrides[dep] = lambda: book
    for dep in (web.memory_store, web_more.memory_store):
        app.dependency_overrides[dep] = lambda: memory
    app.dependency_overrides[web_more.pain_store] = lambda: pain
    c = TestClient(app)
    assert "pain" in [t["kind"] for t in c.get("/iron/api/triggers").json()["triggers"]]
    healed = replace(knee("resolved", 0), updated=at(real) + timedelta(hours=1), created=at(real))
    asyncio.run(memory.apply("42", [Change("insert", item=healed)]))
    assert "pain" not in [t["kind"] for t in c.get("/iron/api/triggers").json()["triggers"]]


def test_the_coach_also_drops_pain_from_before_it_healed() -> None:
    from ironm_agent.coach_state import _gather
    from tests.test_coach import deps

    pain, memory = PainBook(), MemoryBook()
    real = date.today()
    pain.rows["42"] = [
        ("joint.knee", real - timedelta(days=3)),
        ("joint.knee", real - timedelta(days=1)),
    ]
    asyncio.run(
        memory.apply("42", [Change("insert", item=replace(knee("resolved", 0), updated=at(real)))])
    )
    inp = asyncio.run(_gather("42", replace(deps(pain=pain), memory=memory), real))
    assert inp.pains == []


def test_after_it_healed_repeated_pain_is_asked_about_again() -> None:
    pains = [("joint.knee", TODAY - timedelta(days=d)) for d in (1, 5, 9)]
    assert daily_asks([knee("active", 20)], pains, None, [], TODAY) == []  # 还记着：不问
    [ask] = [c.item for c in daily_asks([knee("resolved", 20)], pains, None, [], TODAY) if c.item]
    assert "膝" in ask.content  # 好了以后又反复疼：问要不要记成长期的


def test_case_file_avoids_parts_that_hurt_lately() -> None:
    from ironm_agent.casefile import Snapshot, build
    from ironm_agent.memory_view import Recall
    from ironm_agent.metrics import Profile, Readings

    snap = Snapshot(Profile(), Readings(), (), TODAY)
    assert build(snap, Recall(()), "今晚练什么").sore == ()
    case = build(snap, Recall(()), "今晚练什么", sore=["joint.knee"])
    assert case.sore == ("joint.knee",)  # 给排计划、换动作的工具避开
    assert (
        "joint.knee" not in case.injuries
    )  # 练后酸了几天不算伤病，回答里不写"膝盖有伤"（复核 11-04）


@pytest.mark.parametrize(
    ("text", "kind"),
    [("左膝已经好了", "resolve"), ("左膝不疼了", "resolve"), ("左膝好了但深蹲还有点疼", "update"),
     ("左膝还没好", "update"), ("左膝好了很多", "update"), ("左膝恢复了七八成", "update"),
     ("左膝好多了", "update")],
)  # fmt: skip
@pytest.mark.parametrize("op", ["update", "add"])
def test_saying_an_injury_healed_ends_it(text: str, kind: str, op: str) -> None:
    """更新也好、新增撞上同一处也好，说好了才结束；"好了很多""恢复了七八成"是好转，不是好了（复核 11-04）。"""
    old = knee("active", 10)
    one = {
        "op": op,
        "content": text,
        "quote": text,
        "category": "injury",
        "parts": ["joint.knee"],
        "side": "左",
    }
    [got], bad = validate({"ops": [{**one, "target": "m1"} if op == "update" else one]}, {"m1": old}, text, "",
                          today=TODAY)  # fmt: skip
    assert not bad and got.op == kind and got.target is old, text
    if kind == "resolve":
        assert got.data["parts"] == ["joint.knee"] and got.key == old.key


def test_cough_is_better_does_not_start_another_illness(monkeypatch: Any) -> None:
    """两周模拟（§162）：管家记"好了"，后台又从记忆里认出"咳嗽"开了一次新的生病。§163 起生病只按管家交的写。"""
    from ironm_agent.actions import RECORD_STATE
    from ironm_agent.illness import Episode, IllnessBook
    from tests.fakes import call, jsonr
    from tests.test_single_agent import single
    from tests.test_turn_flow import run as run_turn

    better = {
        "op": "add",
        "category": "event",
        "content": "咳嗽也好了",
        "quote": "咳嗽也好了",
        "lasting": "short",
    }

    def answer(system: str, user: str, results: list[str]) -> Any:
        if not results:
            return call(RECORD_STATE, better="好了")
        if len(results) == 1:
            return call("remember", items=[better])
        return jsonr({"answer": "好了就好，明天按七成练〔经验〕。"})

    a, _ = single(answer, monkeypatch)
    ill = IllnessBook()
    asyncio.run(
        ill.save(
            "42",
            Episode(symptoms=["发烧", "嗓子疼"], level="fever", started=date.today() - timedelta(days=1)),
        )
    )
    a._illness = ill
    run_turn(a, "咳嗽也好了，今天一点症状都没有了")
    asyncio.run(a.settle())
    [only] = ill.rows["42"].values()
    assert only.status == "resolved"  # 只有原来那一次，结束了；没有新开"咳嗽"


def test_risks_follow_the_latest_word() -> None:
    from ironm_agent.casefile import risks
    from ironm_agent.metrics import Readings

    op = replace(knee("active", 30), content="左膝术后", data={**KNEE, "kind": "术后"})
    assert [r.key for r in risks(Readings(), [op], TODAY)] == ["surgery"]
    later = replace(knee("resolved", 1), data={**KNEE, "kind": "术后"})
    assert risks(Readings(), [op, later], TODAY) == ()
