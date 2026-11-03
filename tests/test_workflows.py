"""其余工作流一次改完（spec [2026-10-23] §111）：8 个工作流、全部步骤卡、并掉的内容都在、系统情况不再强装规程。

不调用真实模型。
"""

from __future__ import annotations

from typing import Any

import pytest

from ironm_agent.metrics import Readings
from ironm_agent.skills import CARD_MAX, REF_HEAD, by_id, catalog_any, skills
from tests.fakes import jsonr
from tests.test_single_agent import single
from tests.test_skill_route import ids, routed
from tests.test_turn_flow import book, run, snapshot_of, steady

WORKFLOWS = {"intake-assess": "建档与目标", "plan-build": "排训练计划", "readiness-adjust": "今天练不练",
             "log-review": "记训练与复盘", "pain-injury": "伤痛处理", "diet-plan": "饮食方案",
             "data-read": "数据与化验解读", "move-coach": "动作教学"}  # fmt: skip
GONE = ("goal-set", "comeback", "progress-plateau", "目标设定", "中断后回归", "进展与平台期",
        "记训练与单次复盘", "初次评估")  # fmt: skip


def test_eight_workflows_and_three_cores() -> None:
    folder = {x.id: x.name for x in skills() if x.body}
    assert folder == WORKFLOWS
    assert {x.id for x in skills() if x.core} == {"train-core", "food-core", "rest-core"}
    text = catalog_any()
    assert all(g not in text for g in GONE)


def test_every_workflow_starts_with_a_step_card() -> None:
    for x in skills():
        if not x.body:
            continue
        assert x.card_kind == "步骤卡" and 0 < len(x.card) <= CARD_MAX, x.id
        assert "①" in x.card and "验收" in x.card, x.id
        assert "这份规程用到的工具" not in x.text(), x.id  # 步骤卡每步写了工具，不再另列一行
        names = [n for n, _ in x.sections()]
        assert not any(n == "概要" or n.endswith("·概要") for n in names), x.id  # 步骤卡代替概要
        for n in names:  # 知识类的节都是参考段
            base = n.removeprefix(REF_HEAD).split("·")[-1]
            if base in ("判断规则", "输出", "不同的人", "常见错误", "示例", "要点"):
                assert n.startswith(REF_HEAD), (x.id, n)


def test_merged_bodies_are_all_there() -> None:
    intake, plan, log = by_id("intake-assess"), by_id("plan-build"), by_id("log-review")
    assert intake is not None and plan is not None and log is not None
    assert "设定目标再配上定期看进度" in (intake.section("目标·要点") or "")  # 原目标设定的概要
    assert "〔K57〕" in intake.text(full=True) and (intake.section("目标·步骤") or "")
    assert "〔K84〕" in plan.text(full=True) and "〔K85〕" in (
        plan.section("回归·马上要中断") or ""
    )
    assert "〔K22〕" in log.text(full=True) and (log.section("平台期·步骤") or "")
    for sid, words in (("readiness-adjust", "按状态减量不影响长期进步〔K82〕"),
                       ("intake-assess", "筛查结论不说重也不说轻"),
                       ("diet-plan", "油和酱料容易估少"),
                       ("move-coach", "取「怎么讲」一节的对照")):  # fmt: skip
        x = by_id(sid)
        assert x is not None and words in x.text(full=True) + x.card, sid  # 原决策卡里的话一条不丢


def test_no_pointer_to_names_that_are_gone() -> None:
    for x in skills():
        whole = x.text(full=True) + x.not_for + x.card + x.use
        for name in GONE[3:]:
            assert f"「{name}」" not in whole, (x.id, name)


def test_injury_memory_does_not_force_the_pain_skill(monkeypatch: pytest.MonkeyPatch) -> None:
    from ironm_agent.memory_store import Change, Item, now

    a, s = single(lambda *_: jsonr({"answer": "好。"}), monkeypatch, old=True)
    t = now()
    asyncio_run(a._memory.apply("42", [Change("insert", item=Item(
        "k", "injury", "左膝旧伤", "左膝旧伤", "said", "active", t, t))]))  # fmt: skip
    s.route = routed(["diet-plan"], ["food"])
    _, seen = run(a, "早餐吃什么")
    assert "pain-injury" not in ids(seen) and "diet-plan" in ids(seen)


def test_poor_readiness_does_not_force_the_today_skill(monkeypatch: pytest.MonkeyPatch) -> None:
    tired = Readings(sleep_hours=steady(7.3, last=[4.6, 4.8, 4.5]),
                     resting_hr=steady(58, last=[65, 66, 67]))  # fmt: skip
    a, s = single(lambda *_: jsonr({"answer": "好。"}), monkeypatch, old=True,
                  snapshot=snapshot_of(tired))  # fmt: skip
    a._memory = book(("equipment", "在健身房练"))
    s.route = routed(["diet-plan"], ["food"])
    _, seen = run(a, "早餐吃什么")  # 不是问数据：旧做法这里会强装今天练不练
    assert seen["readiness"] == "poor"
    assert "readiness-adjust" not in ids(seen) and "diet-plan" in ids(seen)


def asyncio_run(x: Any) -> Any:
    import asyncio

    return asyncio.run(x)
