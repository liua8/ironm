"""主教练的调度：规则校验与关键词兜底。"""

import asyncio

from ironm_agent.roles import Role
from ironm_agent.router import keyword_route, route, validate
from tests.fakes import FakeLLM, down, jsonr


def test_valid_model_route_runs_primary_and_helpers() -> None:
    r, problems = validate(
        {"intent": "pro", "primary": "nutrition", "helpers": ["trainer"], "reason": "x"},
        "增肌怎么吃",
    )
    assert problems == [] and r is not None
    assert r.experts() == (Role.NUTRITION, Role.TRAINER)


def test_recovery_goes_before_trainer() -> None:
    r, _ = validate({"intent": "pro", "primary": "trainer", "helpers": ["recovery"]}, "累了还练吗")
    assert r is not None and r.experts() == (Role.RECOVERY, Role.TRAINER)


def test_bad_routes_are_rejected() -> None:
    for raw in (
        {"intent": "pro", "primary": "doctor"},
        {
            "intent": "pro",
            "primary": "trainer",
            "helpers": ["data", "recovery"],
        },  # 数据分析已不是角色
        {"intent": "pro", "primary": "trainer", "helpers": ["chef"]},
        {"intent": "whatever"},
    ):
        r, problems = validate(raw, "问题")
        assert r is None and problems


def test_discomfort_forces_professional_route() -> None:
    # 模型说是闲聊，但这句话提到疼：按专业问题处理，由康复恢复师来答
    r = asyncio.run(route("你好，我膝盖有点疼", [], FakeLLM(lambda *_: jsonr({"intent": "chat"}))))
    assert r.intent == "pro" and "discomfort" in r.concerns and Role.RECOVERY in r.experts()


def test_model_down_falls_back_to_keywords() -> None:
    r = asyncio.run(route("肌酸要怎么吃", [], FakeLLM(down)))
    assert r.by == "keywords" and r.primary is Role.NUTRITION and r.problems


def test_invalid_model_route_falls_back_and_records_reason() -> None:
    llm = FakeLLM(lambda *_: jsonr({"intent": "pro", "primary": "doctor"}))
    r = asyncio.run(route("我最近的静息心率怎么样", [], llm))
    assert r.by == "keywords" and r.primary is Role.RECOVERY  # 心率归康复恢复师
    assert any("doctor" in p for p in r.problems)


def test_keyword_route_for_greetings_and_app_help() -> None:
    assert keyword_route("你好").intent == "chat"
    assert keyword_route("这个app怎么用").intent == "app"
