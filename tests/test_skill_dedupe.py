"""规程去重（spec [2026-10-23] §101）：一件事只写在一处；合并、拆掉的规程里的资料都还在。"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from ironm_agent.memory_store import Change
from ironm_agent.skills import Skill, by_id, skills
from tests.fakes import jsonr
from tests.test_single_agent import single
from tests.test_special import mem
from tests.test_turn_flow import run

# 改之前两份规程的资料编号
SICK_DAYS = {"K23", "K14", "K107", "K108"}
RECOVERY_SLEEP = {"K07", "K34", "K35", "K48", "K49", "K51", "K53", "K54", "K55", "K08", "K113",
                  "K114", "K115", "K116"}  # fmt: skip


def _all(x: Skill) -> str:
    return x.text(full=True) + "\n" + x.card + "\n" + x.not_for


def test_fourteen_skills_and_no_pointer_to_the_old_ones() -> None:
    folder = [x for x in skills() if x.body]
    gone = {"sick-days", "recovery-sleep", "cardio-fitness", "supplements-meds", "special-groups",
            "goal-set", "comeback", "progress-plateau"}  # fmt: skip
    assert len(folder) == 8 and not gone & {x.id for x in skills()}  # §110 拿出三份，§111 收成 8 个
    for x in skills():
        for old in ("「生病期间」", "「恢复与睡眠」", "「按状态调整」", "用「有氧与体能」", "用「补剂与用药」",
                    "按「特殊人群」"):  # fmt: skip
            assert old not in _all(x), (x.id, old)


def test_merged_and_moved_references_are_kept() -> None:
    today = by_id("readiness-adjust")
    rest = by_id("rest-core")
    assert today is not None and rest is not None and today.name == "今天练不练"
    assert set(today.refs_for()) >= SICK_DAYS and today.on == ()  # 不再按"状态差"自动装（§182）
    assert "发烧时不运动" in today.body and "症状消失满 7 天" in today.body
    assert set(rest.refs_for()) >= RECOVERY_SLEEP


def test_cores_keep_only_the_conditions_code_does_not_cover() -> None:
    for x in skills():
        if x.core:
            assert {k for k, _ in x.special} <= {"injury"}, x.id


def test_global_safety_lines_are_not_repeated_in_skills() -> None:
    for x in skills():
        assert not re.search(r"系统会(直接)?给急救指引|不推荐药物", _all(x)), x.id


def test_pregnant_user_gets_the_rules_from_code_and_can_cite_them(monkeypatch: Any) -> None:
    got: dict[str, str] = {}

    def answer(system: str, user: str, results: list[str]) -> Any:
        got.setdefault("all", system + user)
        return jsonr({"answer": "出血、头晕就马上停下〔K24〕。"})

    a, _ = single(answer, monkeypatch, old=True)
    asyncio.run(a._memory.apply("42", [Change("insert", item=mem("怀孕 20 周"))]))
    _, seen = run(a, "今天练什么")
    assert "孕期：不排跳跃类动作" in got["all"]  # 代码带上的硬规则
    assert "这个人的特殊情况：孕期" not in got["all"]  # 基础规程不再重复一遍
    assert seen["kb"] == ["K24"]  # 原来基础规程带进来的资料照样能引用
