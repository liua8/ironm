"""首页动作表跟着管家定的今天走（spec [2026-10-23] §181）：调整过就列调整后的、直接打卡带上调整后的版本。"""

from __future__ import annotations

from pathlib import Path

JS = (Path(__file__).resolve().parents[1] / "ironm_agent" / "web" / "app.js").read_text(
    encoding="utf-8"
)


def test_home_list_follows_the_coach() -> None:
    card = JS[JS.index("function trainCard") : JS.index("// 今天吃（§175 照参照图）")]
    assert "drawList(v.items);" in card
    assert (
        'if (tv.status === "ok" && tv.changed && tv.today) { drawList(tv.today.items); shownVersion = tv.today; }'
        in card
    )
    assert "onStatus: onToday" in card and "doneSheet(v.name, shownVersion)" in card
    assert "比计划少 ${cut} 组" in card  # 少了的组照旧标出来


def test_planned_meal_can_be_logged_as_what_was_actually_eaten() -> None:
    """11-06：按计划排了的那顿，除了"照计划记"还能"记实际吃的"（和空着那顿同一个弹出页）。"""
    plan = JS[JS.index("function todayPlan") : JS.index("// 点空着的那一顿")]
    assert '"照计划记"' in plan
    assert 'onclick: () => addMealSheet(k, d, redraw) }, "吃的不一样？记实际吃的"' in plan
