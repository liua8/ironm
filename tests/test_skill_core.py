"""三个专业 Agent 的提示词提炼成基础规程（spec [2026-10-23] §74）。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ironm_agent.agent import LOAD_SKILL
from ironm_agent.llm import Reply
from ironm_agent.roles import Role
from ironm_agent.skills import core_of, pick_any, skills, with_cores
from tests.fakes import call, jsonr
from tests.test_single_agent import single
from tests.test_turn_flow import run

YAML = Path(__file__).resolve().parents[1] / "ironm_agent" / "skills.yaml"
FLAGS = ("injury", "pregnancy", "bp", "diabetes", "cardiac", "poor")


def test_three_core_skills_hold_the_role_rules() -> None:
    cores = {x.id: x for x in skills() if x.core}
    assert set(cores) == {"train-core", "food-core", "rest-core"}
    train = cores["train-core"]
    assert train.role == Role.TRAINER and train.order.startswith("目标与水平")
    assert any("RPE 8" in r for r in train.rules) and len(train.examples) == 2
    assert (
        "有伤病的部位换动作" in train.text(["injury"]) and "有伤病的部位换动作" not in train.text()
    )
    assert "K33" in train.refs_for(["injury"]) and "K33" not in train.refs_for()


def test_cores_come_with_domain_skills_and_not_for_chat() -> None:
    ids = [x.id for x in pick_any("减脂期怎么练怎么吃")]
    assert ids[:2] == ["train-core", "food-core"]  # 训练在前、饮食在后
    assert pick_any("你好") == []
    assert [x.id for x in with_cores([core_of(Role.RECOVERY)])] == ["rest-core"]  # type: ignore[list-item]


def test_injury_rules_show_only_when_injured(monkeypatch: Any) -> None:
    from ironm_agent.memory_store import Change, Item, now

    a, s = single(lambda *_: jsonr({"answer": "箱式深蹲蹲到不疼的高度〔K33〕。"}), monkeypatch)
    run(a, "深蹲怎么做")
    assert "【训练基础】" in s.system and "这个人的特殊情况" not in s.system
    t = now()
    knee = Item("k", "injury", "左膝旧伤", "左膝旧伤", "said", "active", t, t)
    import asyncio

    asyncio.run(a._memory.apply("42", [Change("insert", item=knee)]))
    _, seen = run(a, "深蹲怎么做")
    assert "这个人的特殊情况：有伤病的部位换动作" in s.system
    assert not seen["_experts"][0]["repaired"]  # 引用 K33 能通过核对


def test_agent_can_load_a_core_skill_and_cite_it(monkeypatch: Any) -> None:
    def answer(system: str, user: str, results: list[str]) -> Reply:
        assert "rest-core（恢复基础）" in system  # 目录里有基础规程
        if not results:
            return call(LOAD_SKILL, id="rest-core")
        assert "【恢复基础】" in results[0] and "思考顺序：分类" in results[0]
        return jsonr({"answer": "练后酸痛 24–72 小时最明显〔K08〕，不是受伤。"})

    a, _ = single(answer, monkeypatch)
    _, seen = run(a, "随便问问")
    assert seen["tools"] == [LOAD_SKILL] and not seen["_experts"][0]["repaired"]


def test_no_role_voice_left_in_skills() -> None:
    text = YAML.read_text()
    body = re.sub(r"(?m)^\s*#.*$", "", text)  # 注释不算
    for phrase in ("交给营养师", "交给康复恢复师", "交给训练教练", "训练教练来排", "交给营养）"):
        assert phrase not in body, phrase
    in_yaml = [
        x for x in skills() if x.role and not x.body
    ]  # 文件夹规程（§76）写在各自的 SKILL.md 里
    assert "\n    role:" not in text and text.count("\n    domain:") == len(in_yaml)
