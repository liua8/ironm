"""首页·干饭改成今天的饮食计划，食谱挪进图鉴（spec [2026-10-23] §125）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from ironm_agent.recipes import recommended, set_of
from tests.test_diet import TODAY, client

JS = (Path(__file__).resolve().parents[1] / "ironm_agent" / "web" / "app.js").read_text()


def test_plan_slots_list_each_food_with_grams_and_kcal(monkeypatch: pytest.MonkeyPatch) -> None:
    c, _, _ = client(monkeypatch)
    s = set_of(TODAY)
    c.put(
        "/iron/api/diet/plan",
        json={
            "set": s,
            "slot": "午餐",
            "ref": {"type": "recipe", "id": "chicken-brown-rice", "servings": 1},
        },
    )
    lunch = c.get("/iron/api/diet/plan").json()["sets"][s]["午餐"]
    rec = next(r for r in recommended() if r.id == "chicken-brown-rice").per_serving()
    assert lunch["foods"] and all(
        f["name"] and f["grams"] > 0 and f["kcal"] >= 0 for f in lunch["foods"]
    )
    assert abs(sum(f["kcal"] for f in lunch["foods"]) - lunch["kcal"]) <= len(
        lunch["foods"]
    )  # 逐样加起来就是这一顿
    assert abs(lunch["carbs_g"] - rec.carbs_g) <= 1 and abs(lunch["fat_g"] - rec.fat_g) <= 1
    assert {
        "type",
        "id",
        "servings",
        "missing",
        "name",
        "kcal",
        "protein_g",
        "image",
    } <= lunch.keys()  # 原有字段不变


def test_diet_page_has_only_three_blocks() -> None:
    page = JS[JS.index("async function food(view)") : JS.index("function mealEntry")]
    assert "recipesCard(" not in page and "tierHref(" not in page and "askChip(" not in page
    assert (
        "todayBudget(" in page
        and "mealEntry(() => today, redraw, null, false)" in page
        and "todayPlan(" in page
    )
    entry = JS[JS.index("function mealEntry") : JS.index("const MAIN_KINDS")]
    assert "withUsual" in entry  # 常吃的只在"＋ 记"弹出页里


def test_each_meal_lists_food_grams_kcal() -> None:
    plan = JS[JS.index("function todayPlan") : JS.index("// 点空着的那一顿")]
    assert "`${Math.round(f.grams)} 克`" in plan and "`${Math.round(f.kcal)} 千卡`" in plan
    assert '"已吃"' in plan and '"照计划记"' in plan and '"没排"' in plan


def test_recipes_live_in_the_atlas() -> None:
    chips = JS[JS.index("const ATLAS_CHIPS") : JS.index("function pageSeg(")]
    assert '["recipes", "食谱"]' in chips  # §136：食谱在图鉴·饮食里
    atlas = JS[JS.index("async function atlas(") : JS.index("async function record(")]
    assert 'chip === "recipes"' in atlas and "recipesPage(view)" in atlas
