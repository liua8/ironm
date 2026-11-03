"""模型先判断，关键词兜底（spec [2026-10-23] §114）：路由、管家给了结果就照它，出错或没写这一项才按关键词。

不调用真实模型。
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from ironm_agent.illness import IllnessBook
from ironm_agent.llm import Reply
from ironm_agent.plan_ops import SCOPE_HINT
from tests.fakes import jsonr
from tests.test_plan_ops import Editor, _card_draft, _seeded
from tests.test_plugin import text_of
from tests.test_single_agent import single
from tests.test_turn_flow import BP_HIGH, Coach, agent, run, snapshot_of


def route(skills: list[str], domains: list[str], **more: Any) -> Any:
    return lambda _: jsonr(
        {"skills": skills, "domains": domains, "intent": "x", "fit": "skill", **more}
    )


def settle(a: Any, text: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """跑一轮并等后台写完状态（同一个事件循环里）。"""
    seen: dict[str, Any] = {}
    a._observe, a._remember_on = seen.update, False

    async def go() -> list[dict[str, Any]]:
        out = [b async for b in a.generate_response("42", [{"role": "user", "content": text}],
                                                       session_id="42:s1")]  # fmt: skip
        await asyncio.gather(*list(a._tasks), return_exceptions=True)
        return out

    return asyncio.run(go()), seen


def test_state_is_written_after_the_answer_from_what_the_agent_judged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ill = IllnessBook()
    at_answer: list[int] = []

    def answer(*_: Any) -> Reply:
        at_answer.append(len(ill.rows.get("42", {})))  # 作答时还没写：关键词不再抢先开记录
        return jsonr({"answer": "发烧就先别练〔经验〕。", "said": {"sick": "发烧"}})

    a, _ = single(answer, monkeypatch, old=True)
    a._illness = ill
    _, seen = settle(a, "我今天发烧了")
    assert at_answer == [0] and seen["state_by"] == "model"
    assert [e.symptoms for e in ill.rows["42"].values()] == [["发烧"]]
    quiet = IllnessBook()
    a, _ = single(lambda *_: jsonr({"answer": "发烧时先别练〔经验〕。"}), monkeypatch, old=True)
    a._illness = quiet
    settle(a, "我今天发烧了")  # 管家作答了却没写 said：就是没说，关键词不另外加
    assert not quiet.rows.get("42")


def test_run_record_says_who_judged(monkeypatch: pytest.MonkeyPatch) -> None:
    a, s = single(lambda *_: jsonr({"answer": "好〔经验〕。"}), monkeypatch, old=True)
    _, seen = run(a, "深蹲怎么做")  # 路由给不出合格结果：关键词兜底
    assert seen["judged_by"] == "keyword" and seen["state_by"] == "model"
    s.route = route(["move-coach"], ["train"])
    _, seen = run(a, "深蹲怎么做")
    assert seen["judged_by"] == "model"
    _, seen = run(_down(monkeypatch), "我今天发烧了")
    assert seen["state_by"] == "keyword"  # 管家这一轮失败：状态按关键词兜底


def _down(monkeypatch: pytest.MonkeyPatch) -> Any:
    a = agent(Coach(down=True), monkeypatch=monkeypatch, snapshot=snapshot_of())
    a._illness = IllnessBook()
    return a


def test_routing_decides_the_skills_and_keywords_add_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, s = single(lambda *_: jsonr({"answer": "好〔经验〕。"}), monkeypatch, old=True)
    s.route = route(["diet-plan"], ["food"])
    _, seen = run(a, "化验单上的肌酐偏高，早餐怎么吃")  # 关键词会另加数据解读；路由没选就不加
    assert "data-read" not in seen["skills"]["general"] and "diet-plan" in seen["skills"]["general"]
    _, seen = run(a, "深蹲完早餐怎么吃")  # 点名了动作：路由没选动作教学就不装
    assert "move-coach" not in seen["skills"]["general"]
    s.route = lambda _: Reply("不是 JSON")
    _, seen = run(a, "深蹲完早餐怎么吃")
    assert "move-coach" in seen["skills"]["general"]  # 路由出错：按关键词
    _, seen = run(a, "化验单上的肌酐偏高，早餐怎么吃")
    assert "data-read" in seen["skills"]["general"]  # 路由出错：按关键词


def test_routing_decides_whether_data_risk_blocks_training(monkeypatch: pytest.MonkeyPatch) -> None:
    def answer(*_: Any) -> Reply:
        return jsonr({"answer": "今天练腿，深蹲 4 组〔经验〕。"})

    a, s = single(answer, monkeypatch, old=True, snapshot=snapshot_of(BP_HIGH))
    s.route = route(["readiness-adjust"], ["train"])
    blocks, seen = run(a, "今天整点啥")  # 没有训练关键词，路由判断是问训练：照样拦
    assert seen["path"] == "risk" and "深蹲 4 组" not in text_of(blocks)
    s.route = route([], ["train"])
    _, seen = run(a, "今天整点啥", session="42:s3")  # 只说了领域是训练，没选规程：也拦
    assert seen["path"] == "risk"
    s.route = route(["diet-plan"], ["food"])
    _, seen = run(
        a, "今天练什么之前先吃点啥", session="42:s2"
    )  # 关键词算问训练，路由判断是问吃：不拦
    assert seen["path"] == "answer"


def test_routing_decides_follow_up_on_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    a, s = single(lambda *_: jsonr({"answer": "58 是近 30 天平均。"}), monkeypatch, old=True)

    async def sources(*_: Any) -> str:
        return "- 静息心率 58：近 30 天平均"

    a._sources = sources
    s.route = route([], [], sources=True)
    run(a, "刚才那个数咋来的")
    assert "追问上一条回答的依据" in s.user + s.system
    s.route = route(["data-read"], ["data"])
    run(a, "这个58是怎么算的")  # 关键词算追问来源，路由说不是：不带
    assert "追问上一条回答的依据" not in s.user + s.system
    s.route = lambda _: Reply("不是 JSON")
    run(a, "这个58是怎么算的")
    assert "追问上一条回答的依据" in s.user + s.system  # 路由出错：按关键词


class Limits(Editor):
    """改计划时管家还交了哪几天没空、改动范围（§114），作为改计划工具的参数（§120）。"""


MOVE = [{"kind": "move", "day": 5, "to_day": 6, "why": "你要求的"}]


def test_plan_edit_limits_follow_the_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    a, _ = _seeded(Limits(MOVE, busy=[6, 7], scope="once"), monkeypatch)
    blocks, seen = run(a, "周末陪孩子，把周五挪到周六")  # 关键词看不出没空，管家看出来了
    assert seen["plan_ops"]["limits_by"] == "model" and "不方便" in text_of(blocks)
    a, store = _seeded(Limits(MOVE, busy=[], scope="always"), monkeypatch)
    blocks, seen = run(a, "这周末出差回来了，把周五挪到周六")  # 关键词会当成周末没空
    assert seen["plan_ops"]["ops"] == 1 and _card_draft(blocks, store).content["hint"] == ""
    a, store = _seeded(Limits(MOVE, busy=[], scope="unclear"), monkeypatch)
    blocks, _ = run(a, "把周五挪到周六，以后都这样")
    assert _card_draft(blocks, store).content["hint"] == SCOPE_HINT  # 按管家的判断，不按"以后都"
    a, store = _seeded(Editor(MOVE), monkeypatch)
    blocks, seen = run(a, "周末出差，把周五挪到周六")  # 管家没写这两项：关键词兜底
    assert seen["plan_ops"]["limits_by"] == "keyword" and "不方便" in text_of(blocks)


def test_edit_instructions_ask_the_agent_for_busy_days_and_scope() -> None:
    from ironm_agent.actions import PLAN_EDIT_SCHEMA

    params = PLAN_EDIT_SCHEMA["function"]["parameters"]["properties"]
    assert "busy" in params and "scope" in params  # 改计划工具里问没空的日子和改动范围


