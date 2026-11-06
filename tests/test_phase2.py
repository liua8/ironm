"""§163 第二期（spec [2026-10-23] §182）。"""

from __future__ import annotations

from pathlib import Path

A = Path(__file__).resolve().parents[1] / "ironm_agent"


def test_answers_go_item_by_item_and_plans_do_not_take_the_first_sentence() -> None:
    """需求 5：没有"计划说明第一句"；有"逐件答"。"""
    texts = {
        p: p.read_text(encoding="utf-8")
        for p in [
            A / "agent.py",
            A / "clarify.py",
            A / "plugin.py",
            A / "skills" / "plan-build" / "SKILL.md",
        ]
    }
    for p, t in texts.items():
        assert "计划说明第一句" not in t, p.name
    assert "逐件答" in texts[A / "agent.py"]
    assert "先逐件答" in texts[A / "skills" / "plan-build" / "SKILL.md"]
