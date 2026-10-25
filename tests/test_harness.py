"""运行框架（spec [2026-10-23] §31 第一步）：轨迹、出错信号与归因、用户反应、系统与个人汇总。不连数据库。"""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ironm_agent import harness
from ironm_agent.harness import Signal, TraceBook, Turn, diagnose, problem_kinds
from tests.test_plugin import Scripted, agent, collect

QUESTION = "我最近的静息心率怎么样"


def kinds(run: dict[str, Any]) -> set[str]:
    return {s.kind for s in diagnose(run)}


def test_problem_kinds_keep_only_categories() -> None:
    got = problem_kinds([
        "「你每周练 5 次…」里的数字 5 在这一句里找不到",
        "引用了不存在的资料或计算编号：K99",
        "带数据编号的句子里，这些数字在所引的数据行里找不到：62",
        "输出不是规定格式的 JSON",
        "这一轮要写出 plan（完整的每周计划）",
    ])  # fmt: skip
    assert got == ["number", "bad_ref", "data_number", "format", "plan_format"]


def test_signals_go_to_the_right_stage() -> None:
    run = {
        "path": "pro", "ms": 25_000, "route_by": "weighted", "model_failures": 1,
        "route": {"weighted": {"trainer": 0.71, "nutrition": 0.6, "recovery": 0.1},
                  "channels": {"llm": {"trainer": 0.9, "nutrition": 0.5},
                               "keyword": {"trainer": 0.2, "nutrition": 0.8}}},
        "_experts": [
            {"role": "trainer", "status": "spoke", "ms": 16_000, "experience": 0.8,
             "fixed": True, "repaired": True, "checks": ["number"], "exhausted": True,
             "mentions": ["nutrition"],
             "calls": [{"tool": "search_knowledge", "result": "empty", "ms": 3},
                       {"tool": "pain_check", "result": "error", "ms": 2},
                       {"tool": "query_health_indicators", "result": "empty", "ms": 9}]},
            {"role": "nutrition", "status": "silent", "calls": []},
        ],
        "_compose": {"checks": ["compose_number"], "repaired": False, "degraded": True},
        "constraints": ["calorie_floor"], "plan_check": "partly",
    }  # fmt: skip
    signals = diagnose(run)
    assert {s.kind for s in signals} >= {
        "route_close", "route_disagree", "route_missed", "kb_empty", "tool_error", "health_empty",
        "query_exhausted", "experience_high", "check_repaired", "slow_expert", "expert_silent",
        "compose_check", "compose_fallback", "constraint", "plan_check", "slow_turn", "model_failure",
    }  # fmt: skip
    stage = {s.kind: (s.stage, s.role) for s in signals}
    assert stage["route_missed"] == ("route", "trainer") and stage["kb_empty"] == (
        "knowledge",
        "trainer",
    )
    assert stage["tool_error"] == ("tool", "trainer") and stage["health_empty"] == (
        "data",
        "trainer",
    )
    assert (
        stage["check_repaired"] == ("answer", "trainer")
        and stage["compose_fallback"][0] == "compose"
    )
    assert "check_fixed" not in stage  # 被规则修正的只记修正，不重复记"改写后通过"
    # 一切正常的一轮：没有信号
    clean = {"path": "pro", "ms": 6_000, "route": {"weighted": {"trainer": 0.9, "recovery": 0.2}},
             "_experts": [{"role": "trainer", "status": "spoke", "ms": 5_000, "experience": 0.2,
                           "calls": [{"tool": "search_knowledge", "result": "ok", "ms": 2}]}],
             "_compose": {}}  # fmt: skip
    assert diagnose(clean) == []


def test_turn_leaves_a_trace_without_content(
    monkeypatch: pytest.MonkeyPatch, traces_in_memory: TraceBook, caplog: pytest.LogCaptureFixture
) -> None:
    answer = "你近 30 天静息心率很稳。<statement>平均 58 次/分<cite>[r1]</cite></statement>，在正常范围。"
    caplog.set_level(logging.INFO)
    blocks = collect(agent(Scripted(answer), monkeypatch=monkeypatch), QUESTION)
    assert blocks  # 回答照常
    [turn] = traces_in_memory.turns
    assert turn.user_id == "42" and turn.session == "42:s1"
    t = turn.trace
    assert t["path"] and t["roles"] == ["recovery"]
    [expert] = t["experts"]
    assert expert["role"] == "recovery" and expert["status"] == "spoke" and expert["rounds"] >= 2
    assert (
        expert["calls"][0]["tool"] == "query_health_indicators"
        and expert["calls"][0]["result"] == "ok"
    )
    assert "experience" in expert and "ms" in expert and "missing" in t
    dumped = json.dumps(turn.trace, ensure_ascii=False) + json.dumps(
        turn.signals, ensure_ascii=False
    )
    for secret in (QUESTION, "很稳", "58.2", "次/分"):  # 原话、回答原文、健康数值都不在轨迹里
        assert secret not in dumped
    line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("ironm turn"))
    assert '"experts"' not in line and "_experts" not in line  # 明细不进日志行


def test_trace_failure_does_not_break_the_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    class Broken(TraceBook):
        async def add(self, turn: Turn) -> None:
            raise RuntimeError("db down")

    monkeypatch.setattr(harness, "_default", Broken())
    blocks = collect(agent(Scripted(), monkeypatch=monkeypatch), QUESTION)
    assert any(b["type"] == "text" for b in blocks)


def test_turn_id_block_is_sent_for_rating(
    monkeypatch: pytest.MonkeyPatch, traces_in_memory: TraceBook
) -> None:
    from ironm_agent.render import TURN_ID

    a = agent(Scripted(), monkeypatch=monkeypatch)

    async def go() -> list[dict[str, Any]]:
        out = [
            b
            async for b in a.generate_response(
                "42", [{"role": "user", "content": QUESTION}], session_id="42:s1"
            )
        ]
        await a.settle()
        return out

    blocks = asyncio.run(go())
    sent = next(b for b in blocks if b.get("id") == TURN_ID)
    assert sent["args"]["turn"] == traces_in_memory.turns[0].id


def test_user_reaction_is_marked_on_the_previous_turn(
    monkeypatch: pytest.MonkeyPatch, traces_in_memory: TraceBook
) -> None:
    a = agent(Scripted(), monkeypatch=monkeypatch)
    said: list[str] = []

    async def history(session_id: str, text: str) -> list[str]:
        return [f"用户：{x}" for x in said]

    a._history = history

    async def ask(text: str) -> None:
        _ = [
            b
            async for b in a.generate_response(
                "42", [{"role": "user", "content": text}], session_id="42:s1"
            )
        ]
        await a.settle()
        said.append(text)

    asyncio.run(ask(QUESTION))
    asyncio.run(ask("我最近的静息心率到底怎么样"))  # 换个说法再问
    asyncio.run(ask("不对，我问的是睡眠"))
    first, second, _third = traces_in_memory.turns
    assert {"kind": "rephrase", "stage": "outcome", "role": "", "detail": ""} in first.signals
    assert any(s["kind"] == "user_says_wrong" for s in second.signals)
    assert harness.user_reaction("帮我排个计划", "我最近的静息心率怎么样") is None


def test_safety_dispute() -> None:
    book = TraceBook()
    book.turns.append(Turn("t1", "42", "s", datetime.now(UTC), {"path": "safety"}))
    assert (
        asyncio.run(harness.react(book, "42", "s", "不是，我说的是以前的事", "胸口痛"))
        == "safety_disputed"
    )
    assert book.turns[0].signals[0]["stage"] == "safety"


def _turn(
    i: int, user: str, signals: list[Signal], experts: list[dict[str, Any]], **trace: Any
) -> Turn:
    return Turn(f"t{i}", user, "s", datetime.now(UTC) - timedelta(hours=i),
                {"path": "pro", "ms": 1000 * (i + 5), "experts": experts, **trace},
                [s.json() for s in signals])  # fmt: skip


def test_system_and_person_summaries() -> None:
    trainer = {"role": "trainer", "status": "spoke", "ms": 4000, "experience": 0.6,
               "calls": [{"tool": "search_knowledge", "result": "empty", "ms": 2}]}  # fmt: skip
    nutrition = {"role": "nutrition", "status": "silent", "ms": 3000, "calls": []}
    turns = [
        _turn(0, "42", [Signal("kb_empty", "trainer"), Signal("rating_down")], [trainer],
              skills={"trainer": ["train-plan"]}, missing=["睡眠"]),
        _turn(1, "42", [Signal("expert_silent", "nutrition"), Signal("rating_up")], [trainer, nutrition],
              skills={"trainer": ["train-plan"], "nutrition": ["food-plan"]}),
        _turn(2, "7", [], [trainer], skills={"trainer": ["train-cardio"]}),
    ]  # fmt: skip
    s = harness.system_summary(turns)
    assert s["turns"] == 3 and s["ms"]["p50"] == 6000
    assert {x["stage"]: x["count"] for x in s["stages"]} == {
        "knowledge": 1,
        "outcome": 1,
        "answer": 1,
    }
    assert s["roles"]["trainer"]["turns"] == 3 and s["roles"]["trainer"]["kb_empty"] == 1
    assert s["roles"]["nutrition"]["silent"] == 1 and s["roles"]["trainer"]["experience"] == 0.6
    assert s["skills"]["train-plan"] == {"loaded": 2, "unhappy": 50.0}
    assert s["tools"]["search_knowledge"] == {"calls": 3, "error": 0, "empty": 3, "refused": 0}
    p = harness.person_summary([t for t in reversed(turns) if t.user_id == "42"], declined=2)
    assert p["turns"] == 2 and p["rating_down"] == 1 and p["rating_up"] == 1
    assert (
        p["worst_role"] in ("训练教练", "营养师")
        and p["missing"] == ["睡眠"]
        and p["declined"] == 2
    )


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, TraceBook, dict[str, str]]:
    from mirobody.server.auth import verify_token

    from ironm_agent import web, web_more

    book = TraceBook()
    who = {"id": "42"}
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: who["id"]
    app.dependency_overrides[web_more.trace_store] = lambda: book
    monkeypatch.setenv("IRONM_ADMINS", "admin-1")
    return TestClient(app), book, who


def test_rating_endpoint_only_for_own_turn(
    api: tuple[TestClient, TraceBook, dict[str, str]],
) -> None:
    c, book, who = api
    book.turns.append(Turn("t1", "42", "s", datetime.now(UTC), {"path": "pro"}))
    assert c.post("/iron/api/turns/t1/rating", json={"rating": -1}).status_code == 200
    assert book.turns[0].signals[0]["kind"] == "rating_down"
    who["id"] = "7"
    assert (
        c.post("/iron/api/turns/t1/rating", json={"rating": 1}).status_code == 404
    )  # 别人的那一轮记不上
    assert c.post("/iron/api/turns/t1/rating", json={"rating": 5}).status_code == 422


def test_summaries_are_admin_only(api: tuple[TestClient, TraceBook, dict[str, str]]) -> None:
    c, book, who = api
    book.turns.append(Turn("t1", "42", "s", datetime.now(UTC), {"path": "pro", "ms": 5000},
                           [Signal("kb_empty", "trainer").json()]))  # fmt: skip
    assert c.get("/iron/api/admin/harness/system").status_code == 403
    assert c.get("/iron/api/admin/harness/person/42").status_code == 403
    who["id"] = "admin-1"
    s = c.get("/iron/api/admin/harness/system?days=7").json()
    assert s["turns"] == 1 and s["signals"][0]["kind"] == "kb_empty"
    p = c.get("/iron/api/admin/harness/person/42").json()
    assert p["turns"] == 1 and p["stages"][0]["stage"] == "knowledge"
    assert c.get("/iron/api/admin/harness/person/7").json()["turns"] == 0


def test_turn_list_shows_only_bad_turns(api: tuple[TestClient, TraceBook, dict[str, str]]) -> None:
    c, book, who = api
    route = {"channels": {"llm": {"nutrition": 0.9, "trainer": 0.2}, "keyword": {"trainer": 0.7}}}
    book.turns += [
        Turn("t1", "42", "s", datetime.now(UTC), {"path": "pro", "ms": 9000, "roles": ["nutrition"],
             "route": route, "skills": {"nutrition": ["food-timing"]}},
             [Signal("check_repaired", "nutrition", "number").json(), Signal("rating_up").json()]),
        Turn("t2", "42", "s", datetime.now(UTC), {"path": "pro", "ms": 5000}, [Signal("rating_up").json()]),
        Turn("t3", "7", "s", datetime.now(UTC), {"path": "pro", "ms": 5000}, [Signal("kb_empty", "trainer").json()]),
    ]  # fmt: skip
    assert c.get("/iron/api/admin/harness/turns").status_code == 403
    who["id"] = "admin-1"
    rows = c.get("/iron/api/admin/harness/turns?person=42").json()["turns"]
    assert [r["id"] for r in rows] == ["t1"]  # 只有好评的那一轮不列
    r = rows[0]
    assert r["roles"] == ["营养师"] and r["route_tops"] == {
        "llm": "nutrition",
        "keyword": "trainer",
    }
    assert r["signals"][0]["name"] == "改写后仍不通过、被规则修正" and r["good"] == ["rating_up"]
    assert len(c.get("/iron/api/admin/harness/turns?bad=false").json()["turns"]) == 3
