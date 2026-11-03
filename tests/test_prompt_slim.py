"""提示词瘦身（spec [2026-10-23] §96）：去掉无关和重复、写明优先级；计划和记录的写法只在涉及训练时给。"""

from __future__ import annotations

import re
from typing import Any

from ironm_agent.agent import LOAD_SKILL
from ironm_agent.llm import Reply
from ironm_agent.skills import catalog_any
from tests.fakes import call, jsonr
from tests.test_single_agent import single
from tests.test_turn_flow import run

PREFETCH = "系统按问题先查好的资料"
ACTIONS = "调用后系统会告诉你结果"  # 计划和记录做法里才有的字样（§120 改成调用工具）


def first_call(q: str, monkeypatch: Any) -> tuple[str, str, dict[str, Any]]:
    got: dict[str, str] = {}

    def answer(system: str, user: str, results: list[str]) -> Reply:
        got.setdefault("system", system)
        got.setdefault("user", user)
        return jsonr({"answer": "好。"})

    a, _ = single(answer, monkeypatch, old=True)
    _, seen = run(a, q)
    return got["system"], got["user"], seen


def test_precedence_compact_memory_and_catalog(monkeypatch: Any) -> None:
    system, user, _ = first_call("你好", monkeypatch)
    assert "安全规则（急症、就医、不诊断不开药）> 回答格式" in system
    memory = re.search(r"记忆（他这句话说了.*?(?=\n\n)", system, re.S)
    assert memory is not None and len(memory.group(0)) < 700  # 原来约 1000 字
    assert (
        "plan-build：要每周计划、改计划、停练回来" in catalog_any() and "（" not in catalog_any()
    )  # 目录列编号和一句什么时候用（§110 第 0 层），不再重复名字
    assert len(system) < 3500 and PREFETCH not in user  # 闲聊：系统提示 3500 字以内、不预取
    assert "今天是" not in user  # 日期只在档案里写


def test_actions_only_when_training_and_prefetch_rules(monkeypatch: Any) -> None:
    food, food_user, seen = first_call("早餐吃什么", monkeypatch)
    assert (
        ACTIONS not in food
        and "先用 load_skill 装 plan-build" in food
        and not seen["actions_prompt"]
    )
    assert PREFETCH not in food_user  # 装了内容规程：不按字面预取
    plan, _, seen = first_call("帮我排个增肌计划", monkeypatch)
    assert ACTIONS in plan and seen["actions_prompt"]
    _, squat_user, _ = first_call("深蹲怎么做", monkeypatch)
    assert PREFETCH in squat_user and re.search(
        r"\[K9\d\d", squat_user
    )  # 点到的动作照旧带上动作库条目


def test_loading_a_training_skill_brings_the_actions_back(monkeypatch: Any) -> None:
    results: list[str] = []

    def answer(system: str, user: str, got: list[str]) -> Reply:
        if not got:
            return call(LOAD_SKILL, id="plan-build")
        results.extend(got)
        return jsonr({"answer": "好。"})

    a, _ = single(answer, monkeypatch, old=True)
    run(a, "早餐吃什么")
    assert "【排训练计划】" in results[0] and "计划和训练记录（只在需要时做）" in results[0]
    assert "装上后多了这些工具：propose_new_plan" in results[0]  # 动作工具跟着规程一起装（§120）
