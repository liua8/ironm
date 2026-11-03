"""Skill 按意图装载（spec [2026-10-23] §75）：意图识别路由到规程；没有这类规程时只带基础规程或不装。"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import Any

from ironm_agent.llm import ModelUnavailable, Reply
from ironm_agent.metrics import Readings
from ironm_agent.roles import Role
from ironm_agent.skill_route import Routed, catalog, parse, route
from tests.fakes import jsonr
from tests.test_single_agent import single
from tests.test_turn_flow import TODAY, run, snapshot_of


def routed(skills: list[str], domains: list[str], fit: str = "skill", intent: str = "x") -> Any:
    return lambda _: jsonr({"skills": skills, "domains": domains, "intent": intent, "fit": fit})


def ids(seen: dict[str, Any]) -> list[str]:
    return list(seen["skills"]["general"])


def test_catalog_lists_content_skills_only() -> None:
    text = catalog()
    assert "plan-build 排训练计划" in text and "不用于" in text
    assert "train-core" not in text and "move-feel" not in text  # 基础、讲法规程由系统自己带


def test_parse_keeps_known_ids_and_drops_the_rest() -> None:
    got = parse({"skills": ["plan-build", "no-such", "train-core", "plan-build"],
                 "domains": ["train", "x"], "intent": "想把屁股练翘的增肌训练", "fit": "skill"})  # fmt: skip
    assert got is not None and [x.id for x in got.skills] == ["plan-build"] and got.dropped == 3
    assert got.domains == (Role.TRAINER,) and got.intent == "想把屁股练翘的增肌训"  # 最多 10 个字
    assert parse({"skills": [], "fit": "maybe"}) is None and parse("x") is None
    chat = parse({"skills": ["plan-build"], "domains": ["train"], "intent": "", "fit": "chat"})
    assert chat is not None and chat.skills == () and chat.domains == ()


def test_intent_routes_to_a_skill_with_other_words(monkeypatch: Any) -> None:
    a, s = single(
        lambda *_: jsonr({"answer": "臀桥和保加利亚分腿蹲为主〔经验〕。"}), monkeypatch, old=True
    )
    s.route = routed(["plan-build"], ["train"], intent="臀部增肌")
    _, seen = run(a, "想把屁股练翘")
    assert ids(seen) == ["train-core", "plan-build"] and "【排训练计划】" in s.system
    assert seen["skills_by"] == "route" and seen["skill_intent"] == "臀部增肌"
    assert seen["skill_fit"] == "skill" and "想把屁股练翘" in s.routes[0]
    assert "想把屁股练翘" not in json.dumps({k: v for k, v in seen.items() if not k.startswith("_")},
                                         ensure_ascii=False)  # 运行记录没有原话  # fmt: skip


def test_situation_skills_go_first_and_total_is_capped(monkeypatch: Any) -> None:
    from ironm_agent.memory_store import Change, Item, now

    a, s = single(lambda *_: jsonr({"answer": "先避开深蹲〔经验〕。"}), monkeypatch)
    t = now()
    asyncio.run(a._memory.apply("42", [Change("insert", item=Item(
        "k", "injury", "左膝旧伤", "左膝旧伤", "said", "active", t, t))]))  # fmt: skip
    s.route = routed(["plan-build", "diet-plan", "move-coach"], ["train", "food"])
    _, seen = run(a, "增肌怎么练腿")
    content = [x for x in ids(seen) if not x.endswith("-core") and x != "move-feel"]
    assert content == ["plan-build", "diet-plan", "move-coach"]  # 路由选的，合起来 3 份
    # §111：有伤病不再强装伤痛处理（伤病的处理写在排计划、动作教学的步骤里，训练基础带伤病规则）
    assert "按伤病部位" in s.system or "伤处受力的换掉" in s.system
    assert {"train-core", "food-core"} <= set(ids(seen)) and "rest-core" not in ids(seen)
    assert "有伤病的部位换动作" in s.system  # 有伤病：训练基础带着伤病规则（不靠强装伤痛处理）


def test_no_matching_skill_brings_only_the_core(monkeypatch: Any) -> None:
    a, s = single(
        lambda *_: jsonr({"answer": "孕期先问医生，再降强度〔经验〕。"}), monkeypatch, old=True
    )
    s.route = routed([], ["train"], fit="core", intent="孕期训练")
    _, seen = run(a, "孕期还能卧推吗")
    assert [x for x in ids(seen) if x != "move-feel"] == ["train-core"]  # 讲法规程照旧按说法带
    assert seen["skill_fit"] == "core"
    assert seen["skill_intent"] == "孕期训练"


def test_outside_and_chat_load_nothing(monkeypatch: Any) -> None:
    for fit, text in (("outside", "帮我写个周报"), ("chat", "谢谢你")):
        a, s = single(lambda *_: jsonr({"answer": "好的〔经验〕"}), monkeypatch, old=fit == "chat")
        s.route = routed(["plan-build"], ["train"], fit=fit)  # 无关的事：新用户也不装评估
        _, seen = run(a, text)
        assert ids(seen) == [] and seen["skill_fit"] == fit


def test_router_failure_falls_back_to_keywords(monkeypatch: Any) -> None:
    a, _ = single(lambda *_: jsonr({"answer": "每周练 3 次〔K03〕。"}), monkeypatch)
    _, seen = run(a, "增肌一周练几次")  # 默认的假模型给不出合格的路由结果
    assert seen["skills_by"] == "rule" and "plan-build" in ids(seen)


def test_route_times_out_and_model_errors_return_none(monkeypatch: Any) -> None:
    from ironm_agent import skill_route

    class Slow:
        def __init__(self) -> None:
            self.calls: list[Any] = []

        async def chat(self, *_: Any, **__: Any) -> Reply:
            await asyncio.sleep(1)
            return jsonr({"skills": [], "fit": "chat"})

    class Down(Slow):
        async def chat(self, *_: Any, **__: Any) -> Reply:
            raise ModelUnavailable("x")

    monkeypatch.setattr(skill_route, "TIMEOUT_S", 0.05)
    assert asyncio.run(route(Slow(), "你好")) is None
    assert asyncio.run(route(Down(), "你好")) is None


def test_data_risk_still_blocks_when_the_model_misses_the_points(monkeypatch: Any) -> None:
    bp = Readings(systolic=((TODAY - timedelta(days=2), 186.0),),
                  diastolic=((TODAY - timedelta(days=2), 114.0),))  # fmt: skip
    a, _s = single(lambda *_: jsonr({"answer": "x"}), monkeypatch, snapshot=snapshot_of(bp))
    _, seen = run(a, "今天练什么")
    assert seen["path"] == "risk" and seen["risk_by"] == "fixed"  # §86：话交给模型，没说到退回


def test_routed_dataclass_defaults() -> None:
    assert Routed().fit == "skill" and Routed().skills == ()
