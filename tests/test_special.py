"""特殊人群改成代码硬拦（spec [2026-10-23] §95）：未成年、孕期、心脏病、高血压按硬规则查计划，60 岁以上只提示。"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

from ironm_agent.actions import NEW_PLAN
from ironm_agent.casefile import risks
from ironm_agent.live import Live, LiveItem, LiveSet
from ironm_agent.live_adjust import adjust
from ironm_agent.llm import Reply
from ironm_agent.memory_store import Change, Item, now
from ironm_agent.metrics import Profile, Readings
from ironm_agent.protools.plan_check import check_plan
from ironm_agent.special import flags, is_special, no_heavier, plan_problems, rules_text
from ironm_agent.training import Plan
from tests.fakes import FakeLLM, call, jsonr
from tests.test_plugin import text_of
from tests.test_single_agent import NEW, cards, single
from tests.test_turn_flow import run

TODAY = date.today()


def plan(*items: tuple[str, str], days: int = 1) -> Plan:
    return Plan.model_validate({"title": "x", "days_per_week": days, "sessions": [
        {"day": d, "name": f"练{d}", "items": [{"exercise": e, "sets": 3, "reps": r} for e, r in items]}
        for d in range(1, days + 1)]})  # fmt: skip


def mem(text: str) -> Item:
    t = now()
    return Item("m1", "injury", text, text, "said", "active", t, t)


def born(years: int) -> Profile:
    return Profile(height_cm=170, birth=TODAY - timedelta(days=365 * years + 30), sex="female",
                   goal="health", activity="light")  # fmt: skip


def test_conditions_are_read_from_age_memory_and_blood_pressure() -> None:
    assert flags(born(16), (), TODAY) == {"minor"} and flags(born(65), (), TODAY) == {"senior"}
    assert flags(born(30), (), TODAY) == frozenset()
    bp = Readings(
        systolic=((TODAY - timedelta(days=3), 165.0),),
        diastolic=((TODAY - timedelta(days=3), 102.0),),
    )
    got = flags(born(30), risks(bp, [mem("怀孕 20 周"), mem("去年放了心脏支架")], TODAY), TODAY)
    assert got == {"pregnancy", "cardiac", "hypertension"}


def test_hard_rules_per_condition() -> None:
    heavy = plan(("杠铃深蹲", "3–5"), ("平板支撑", "30 秒"), days=4)
    probs, hints = plan_problems(heavy, {"minor"})
    assert any("每周排了 4 练" in p for p in probs) and any(
        "杠铃深蹲每组 3–5 次" in p for p in probs
    )
    assert not any("平板支撑" in p for p in probs)  # 计时的不算次数
    probs, _ = plan_problems(plan(("波比跳", "10"), ("高脚杯深蹲", "6–8")), {"pregnancy"})
    assert any("波比跳是跳跃类" in p for p in probs) and any("至少 8 次" in p for p in probs)
    assert len(plan_problems(plan(("杠铃卧推", "6–8")), {"cardiac"})[0]) == 1
    assert len(plan_problems(plan(("杠铃卧推", "6–8")), {"hypertension"})[0]) == 1
    assert not plan_problems(plan(("杠铃卧推", "8–12")), {"cardiac", "hypertension"})[0]
    probs, hints = plan_problems(plan(("杠铃深蹲", "3–5")), {"senior"})
    assert not probs and "平衡" in hints[0]  # 60 岁以上只提示
    checked = check_plan(plan(("杠铃深蹲", "3–5")), special={"minor"})
    assert any(is_special(p) for p in checked.problems)
    assert not check_plan(plan(("杠铃深蹲", "3–5"))).problems or not any(
        is_special(p) for p in check_plan(plan(("杠铃深蹲", "3–5"))).problems
    )  # 普通人不按这些拦
    assert "孕期" in rules_text({"pregnancy"}) and rules_text(()) == ""
    assert no_heavier({"minor"}) and not no_heavier({"senior"})


def test_plan_preview_is_blocked_when_the_fix_still_breaks_the_rule(monkeypatch: Any) -> None:
    bad = {**NEW, "sessions": [{**NEW["sessions"][0], "items": [{"exercise": "高脚杯深蹲", "sets": 3, "reps": "4–6"}]},
                               *NEW["sessions"][1:]]}  # fmt: skip

    seen_all: list[str] = []

    def answer(system: str, user: str, results: list[str]) -> Reply:
        seen_all.append(system + user)
        if "上一轮你列了排新计划要用的条件" not in system:  # 还没确认：它先列条件
            return jsonr({"answer": "排新计划前先确认一下：目标减脂、每周 3 练，对吗？"})
        if len(results) < 2:  # 交计划；被硬规则退回后改不掉、照原样再交（§120）
            return call(NEW_PLAN, plan=bad, changes="三练全身", kind="new")
        return jsonr({"answer": "每周 3 次全身力量。"})

    a, _ = single(answer, monkeypatch, old=True)
    asyncio.run(a._memory.apply("42", [Change("insert", item=mem("怀孕 20 周"))]))
    first, _ = run(a, "给我一份训练计划")

    async def asked(*_: str) -> list[str]:
        return ["用户：给我一份训练计划", "教练（要点）：" + text_of(first)[:200]]

    a._history = asked
    blocks, seen = run(a, "按这个排")
    assert any("孕期：不排跳跃类动作" in x for x in seen_all)  # 一开始就告诉模型
    assert seen["preview"] == "blocked_special" and not cards(blocks)
    text = text_of(blocks)
    assert (
        "不适合你现在情况" in text and "高脚杯深蹲" in text and "K110" not in text
    )  # 用户看不到编号


def test_live_adjust_never_goes_heavier_for_these_conditions() -> None:
    live = Live(id="x", started=__import__("datetime").datetime.now(), updated=__import__("datetime").datetime.now(),
                items=[LiveItem(exercise="杠铃卧推", sets=[LiveSet(weight_kg=40, reps=10, done=True), LiveSet(weight_kg=40, reps=10)])])  # fmt: skip
    llm = FakeLLM(
        lambda *_: jsonr(
            {"say": "加一点", "changes": [{"kind": "all", "item": 1, "weight_kg": 42.5}]}
        )
    )
    got = asyncio.run(adjust(llm, live, "太轻了", 0, "x", special=frozenset({"pregnancy"})))
    assert got.live.items[0].sets[1].weight_kg == 40
    got = asyncio.run(adjust(llm, live, "太轻了", 0, "x"))
    assert got.live.items[0].sets[1].weight_kg == 42.5  # 普通人照常可以加一档


def test_tools_and_daily_review_apply_the_rules(monkeypatch: Any) -> None:
    from ironm_agent import review
    from ironm_agent.protools.registry import ToolContext
    from ironm_agent.protools.registry import run as run_tool
    from ironm_agent.protools.templates import plan_templates
    from tests.test_review import model, setup

    heavy = {"title": "x", "days_per_week": 1, "sessions": [
        {"day": 1, "name": "腿", "items": [{"exercise": "杠铃深蹲", "sets": 3, "reps": "3–5"}]}]}  # fmt: skip
    got = asyncio.run(
        run_tool("check_plan", ToolContext(TODAY, special=frozenset({"minor"})), {"plan": heavy})
    )
    assert any("未满 18 岁" in p for p in got.problems)  # 计划检查工具带上情况
    lib = plan_templates(level="6m-2y", goal="muscle", days=3, minutes=60, place="gym", age=30,
                         equipment=None, special={"hypertension"})  # fmt: skip
    assert any("问题：有高血压" in n for n in lib.notes)  # 方案库出的初步方案也按硬规则查
    # 管家复盘：原计划本来就有的（深蹲 6–8 次）不挡减量；改出新的大重量才挡
    bp = Readings(
        systolic=((TODAY - timedelta(days=3), 165.0),),
        diastolic=((TODAY - timedelta(days=3), 102.0),),
    )
    dp = setup(bp)
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe))
    f = next(x for x in seen[0].split("\n") if "当前计划" in x).split("]")[0].lstrip("[")
    day = TODAY.isoweekday()
    lighter, _ = model({"type": "plan", "why": "血压偏高先减量", "basis": [f],
                        "ops": [{"kind": "reduce", "day": day, "ratio": 0.7}]})  # fmt: skip
    assert asyncio.run(review.run("42", dp, lighter, force=True)).done
    heavier, _ = model({"type": "plan", "why": "x", "basis": [f],
                        "ops": [{"kind": "edit", "day": day, "exercise": "罗马尼亚硬拉", "sets": 3, "reps": "3–5"}]})  # fmt: skip
    assert not asyncio.run(review.run("42", dp, heavier, force=True)).done
