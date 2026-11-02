"""规程改写成决策卡（spec [2026-10-23] §99）：装载时只放决策卡和分节目录，细节按节取，依据照旧能引用。"""

from __future__ import annotations

import re
from typing import Any

from ironm_agent.agent import LOAD_SKILL
from ironm_agent.llm import Reply
from ironm_agent.skills import CARD_MAX, by_id, prompt_of, skills
from tests.fakes import call, jsonr
from tests.test_single_agent import single
from tests.test_turn_flow import run

_REF = re.compile(r"〔(K\d{2,4})〕")


def test_every_folder_skill_has_a_short_card_drawn_from_its_own_body() -> None:
    folder = [x for x in skills() if x.body]
    assert len(folder) == 14
    for x in folder:
        assert 0 < len(x.card) <= CARD_MAX, x.id
        assert "## 决策卡" not in x.body and x.body.startswith("## 概要"), x.id  # 正文原样留作细节
        cited = set(_REF.findall(x.card))
        assert cited <= set(_REF.findall(x.body)), (x.id, cited - set(_REF.findall(x.body)))


def test_loading_shows_the_card_and_the_section_index_only() -> None:
    x = by_id("plan-build")
    assert x is not None
    shown = prompt_of([x])
    assert "【排训练计划】（决策卡）" in shown and x.card in shown
    assert "5 ② 调 `plan_templates` 选初步方案" in shown  # 分节目录：编号加节名
    assert "凯圣王" not in shown  # 方案库那张表在细节里
    assert len(shown) < len(x.body) / 2


def test_sections_by_number_name_or_all() -> None:
    x = by_id("plan-build")
    assert x is not None
    by_num = x.section("5")
    assert by_num is not None and by_num.startswith("【排训练计划 · ② 调") and "凯圣王" in by_num
    assert x.section("选初步方案") == by_num and x.section("②") == by_num
    whole = x.section("全部")
    assert whole is not None and "凯圣王" in whole and "## 示例" in whole
    assert x.section("没有这节") is None and x.section("99") is None


def test_agent_can_fetch_a_section_and_cite_from_the_details(monkeypatch: Any) -> None:
    got: list[str] = []

    def answer(system: str, user: str, results: list[str]) -> Reply:
        if not results:
            return call(LOAD_SKILL, id="plan-build", section="选初步方案")
        got.extend(results)
        return jsonr({"answer": "分化和全身，训练量一样时效果差不多〔K62〕。"})

    a, _ = single(answer, monkeypatch, old=True)
    _, seen = run(a, "我想练分化还是全身好，排计划用哪种")
    assert "plan-build" in seen["skills"]["general"]  # 系统选中，只放了决策卡
    assert got and "凯圣王" in got[0]  # 按节取到了细节
    assert seen["kb"] == ["K62"]  # K62 只在细节里，照样通过核对
    assert "K62" not in by_id("plan-build").card  # type: ignore[union-attr]


def test_unknown_section_returns_the_index(monkeypatch: Any) -> None:
    got: list[str] = []

    def answer(system: str, user: str, results: list[str]) -> Reply:
        if not results:
            return call(LOAD_SKILL, id="pain-injury", section="第十节")
        got.extend(results)
        return jsonr({"answer": "好。"})

    a, _ = single(answer, monkeypatch, old=True)
    run(a, "早餐吃什么")
    assert got and got[0].startswith("没有这一节。伤痛处理的分节：1 概要｜2 先要知道")
