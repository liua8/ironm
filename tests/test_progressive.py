"""规程改成工作流 + 渐进式披露（spec [2026-10-23] §110）：四层各放什么、三份主题规程的内容去了哪、每轮更短。

不调用真实模型。
"""

from __future__ import annotations

from typing import Any

import pytest

from ironm_agent.agent import LOAD_SKILL
from ironm_agent.skills import BRIEF_MAX, by_id, catalog_any, prompt_of, skills
from tests.fakes import call, jsonr
from tests.test_prompt_slim import first_call
from tests.test_single_agent import single
from tests.test_skill_route import routed
from tests.test_turn_flow import run

# 改之前（§110 动手前用同一个假模型量的）一轮系统提示的字数
BEFORE = {"你好": 3467, "帮我排个增肌计划": 6172, "今天练什么": 5979}


def test_layer0_catalog_has_a_brief_for_every_skill() -> None:
    text = catalog_any()
    for x in skills():
        if x.style:
            continue
        assert 0 < len(x.brief) <= BRIEF_MAX, x.id
        assert f"{x.id}：{x.brief}" in text
    for gone in ("cardio-fitness", "supplements-meds", "special-groups"):
        assert gone not in text and by_id(gone) is None


def test_layer1_plan_build_is_a_step_card_and_cores_carry_no_examples() -> None:
    plan = by_id("plan-build")
    assert plan is not None and plan.card_kind == "步骤卡"
    for step in ("①", "②", "③", "④", "⑤", "⑥", "验收（代码查）"):
        assert step in plan.card
    for tool in ("plan_templates", "check_plan", "find_substitutes", "estimate_strength"):
        assert tool in plan.card
    shown = prompt_of([plan])
    assert "【排训练计划】（步骤卡）" in shown and "凯圣王" not in shown  # 方案库那张表在第 2 层
    train = by_id("train-core")
    assert train is not None
    each_turn = train.text()
    assert "示例：" not in each_turn and "一周练六天对吗" not in each_turn  # 示例不每轮带
    assert "参考段：有氧、特殊人群、示例" in each_turn  # 参考段目录在，问到先取


def test_layer2_references_can_be_fetched_and_cited() -> None:
    plan, train, food = by_id("plan-build"), by_id("train-core"), by_id("food-core")
    assert plan is not None and train is not None and food is not None
    assert "参考 9 不同的人｜10 排有氧｜11 常见错误｜12 示例" in plan.index()
    steps = plan.index().split("；参考")[0]
    assert steps.startswith("步骤 1 ") and "8 ⑥ 怎么说" in steps and "不同的人" not in steps  # 两组不混
    cardio = plan.section("排有氧") or ""
    assert "〔K40〕" in cardio and "说话测试" in cardio
    assert "每周 150–300 分钟中等强度" in (train.section("有氧") or "")
    special = train.section("特殊人群") or ""
    assert "立即停止并就医" in special and "避开仰卧" in special and "〔K110〕" in special
    supp = food.section("补剂与用药") or ""
    assert "肌酸每天 3–5 克〔K10〕" in supp and "维生素 D" in supp
    assert "一周练六天对吗" in (train.section("示例") or "")
    refs = set(train.refs_for()) | set(food.refs_for())  # 取参考段时引用的编号能通过核对
    assert {"K24", "K110", "K109", "K65", "K69", "K10", "K11", "K94"} <= refs


def test_safety_lines_are_in_the_cores_every_turn() -> None:
    train, food = by_id("train-core"), by_id("food-core")
    assert train is not None and food is not None
    assert "运动中胸痛、头晕、心慌、明显气短：立即停下，尽快就医〔K14〕" in train.text()
    each = food.text()
    assert "不建议改药停药" in each and "吃补剂前先问医生或药师" in each


def test_no_skill_points_to_the_removed_ones() -> None:
    for x in skills():
        whole = x.text(full=True) + x.not_for + x.card
        for old in ("「有氧与体能」", "「补剂与用药」", "「特殊人群」"):
            assert old not in whole, (x.id, old)


def test_agent_fetches_a_core_reference_and_cites_it(monkeypatch: pytest.MonkeyPatch) -> None:
    got: list[str] = []

    def answer(system: str, user: str, results: list[str]) -> Any:
        if not results:
            return call(LOAD_SKILL, id="train-core", section="特殊人群")
        got.extend(results)
        return jsonr({"answer": "能练，每周累计 150 分钟中等强度就合适〔K24〕。"})

    a, _ = single(answer, monkeypatch, old=True)
    _, seen = run(a, "孕妇能练深蹲吗")
    assert got and got[0].startswith("【训练基础 · 参考：特殊人群】")
    assert not seen["_experts"][0]["repaired"]  # 引的编号核对通过


@pytest.mark.parametrize("q, route", [("你好", None), ("帮我排个增肌计划", ["plan-build"]),
                                      ("今天练什么", ["readiness-adjust"])])  # fmt: skip
def test_each_turn_is_not_longer_than_before(
    q: str, route: list[str] | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests import test_single_agent as t

    plain = t.single

    def with_route(answer: Any, mp: Any, **kw: Any) -> Any:
        a, s = plain(answer, mp, **kw)
        if route is not None:
            s.route = routed(route, ["train"])
        return a, s

    monkeypatch.setattr("tests.test_prompt_slim.single", with_route)
    system, _, _ = first_call(q, monkeypatch)
    assert len(system) <= BEFORE[q], (q, len(system))
