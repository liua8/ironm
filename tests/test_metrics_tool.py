"""问答调用指标计算：哪些角色能用、计算编号与数字核对。"""

import asyncio
from datetime import date

from ironm_agent import metrics as m
from ironm_agent.checks import check_text
from ironm_agent.kb import default_kb
from ironm_agent.llm import ToolCall
from ironm_agent.roles import SPECS, Role
from ironm_agent.tools import METRICS, Toolbox

BMI = m.bmi((date(2026, 9, 14), 69.2), 175)
MISSING = m.sleep(())


async def source() -> list[m.Metric]:
    return [BMI, MISSING]


def box(role: Role) -> Toolbox:
    return Toolbox(
        SPECS[role], kb=default_kb(), health=None, user_id="1", session_id="1:s", metrics=source
    )


def test_only_some_roles_can_compute_metrics() -> None:
    assert any(s["function"]["name"] == METRICS for s in box(Role.NUTRITION).schemas())
    assert not any(s["function"]["name"] == METRICS for s in box(Role.EXERCISE).schemas())


def test_metrics_get_calc_ids_and_missing_ones_none() -> None:
    tb = box(Role.DATA)
    text = asyncio.run(tb.run(ToolCall("c1", METRICS, {})))
    assert "[C1] BMI：22.6" in text and "睡眠时长：算不出来" in text
    assert list(tb.evidence.calcs) == ["C1"]


def test_calc_reference_traces_numbers() -> None:
    calcs = {"C1": "BMI：22.6，正常（18.5–23.9）。计算：体重 69.2 公斤 ÷ 身高 1.75 米的平方 = 22.6"}
    assert (
        check_text(
            "你的 BMI 是 22.6，在正常范围〔C1〕。",
            support={},
            entries={},
            question="q",
            calcs=calcs,
        )
        == []
    )
    assert check_text("你的 BMI 是 25.1〔C1〕。", support={}, entries={}, question="q", calcs=calcs)
    assert check_text("你的 BMI 是 22.6〔C9〕。", support={}, entries={}, question="q", calcs=calcs)
