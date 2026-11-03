"""没问的不答（spec [2026-10-23] §112）：来源区不展开计划、不漏给模型的指令；做法只在问怎么做时写；
参考段要取；核对改正不外露。不调用真实模型。"""

from __future__ import annotations

from typing import Any

import pytest

from ironm_agent.answer_format import SLOTS_PROMPT
from ironm_agent.compose import Composed
from ironm_agent.render import shown, sources_text
from ironm_agent.skills import by_id
from tests.fakes import jsonr
from tests.test_single_agent import single
from tests.test_turn_flow import run

PLAN_DETAIL = (
    "计划与训练记录：当前计划：《居家减脂四练》每周 4 练，目标减脂；周一 全身力量A（约 40 分钟）：高脚杯深蹲 "
    "3×10–15（哑铃10–15公斤）；今天的全身力量A已打卡完成：今天的训练任务已经完成，不要再安排今天怎么练；"
    "问今天就只答今天已经练完（这时做法和下一步都留空）"
)


def test_sources_show_only_the_plan_name_not_the_moves_or_instructions() -> None:
    assert shown(PLAN_DETAIL) == "计划与训练记录：当前计划：《居家减脂四练》每周 4 练，目标减脂"
    composed = Composed("整体不错〔C9〕。", (), 0, calcs=(("C9", PLAN_DETAIL),))
    text = sources_text(composed)
    for leak in ("高脚杯深蹲", "不要再安排", "留空", "周一"):
        assert leak not in text, leak
    bmi = "BMI：21.9，正常（18.5–23.9）。计算：体重 ÷ 身高的平方。"
    assert shown(bmi) == bmi  # 别的来源照旧


def test_steps_only_when_he_asks_how() -> None:
    assert "只在他问怎么做、要安排或推荐时写" in SLOTS_PROMPT and "其余留空" in SLOTS_PROMPT


def test_cores_say_to_fetch_the_reference_every_turn() -> None:
    train, food = by_id("train-core"), by_id("food-core")
    assert train is not None and food is not None
    assert "孕产、老人、未成年、慢病的人怎么练：先取参考段再答，不说给不了" in train.text()
    assert "问补剂、用药：先取参考段再答" in food.text()


def test_check_retry_is_marked_as_the_system_and_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def answer(system: str, user: str, results: list[str]) -> Any:
        calls.append(1)
        if len(calls) == 1:  # 第一版引了不存在的编号：核对不过，要改
            return jsonr({"answer": "每周练 3 次就够〔K999〕。"})
        return jsonr({"answer": "每周练 3 次就够〔经验〕。"})

    a, s = single(answer, monkeypatch, old=True)
    seen_msgs: list[list[str]] = []
    plain_call = type(s).__call__

    def spy(self: Any, stage: Any, messages: Any, tools: bool) -> Any:
        if stage == "expert":
            seen_msgs.append([str(m.get("content")) for m in messages])
        return plain_call(self, stage, messages, tools)

    monkeypatch.setattr(type(s), "__call__", spy)
    run(a, "一周练几次")
    assert len(seen_msgs) >= 2
    retry = seen_msgs[1][-1]
    assert retry.startswith(
        "（系统核对，不是用户说的；用户看不到你上一版和这条。直接改正，回答里不提格式、不道歉）"
    )


def test_asking_how_it_is_gets_a_judgement_not_added_training() -> None:
    """§115：问"计划怎么样"只答判断、点出最要紧的不足，不列加练；说要改才写做法、按改计划出预览。"""
    assert "问怎么样、好不好时留空，不足在答案里点一句" in SLOTS_PROMPT
    plan = by_id("plan-build")
    assert plan is not None
    assert "只问计划怎么样、要不要调：不走上面的步骤" in plan.card
    assert "不列改法、不排加练、不讲进阶；他说要改再用 `propose_plan_edit` 出预览" in plan.card
