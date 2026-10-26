"""饮食页：拍 / 填两个入口，记完再选餐次，每种餐每天一份（spec [2026-10-23] §43）。"""

from pathlib import Path
from typing import Any

import pytest

from ironm_agent.meals import MEAL_KINDS, Macros, Meal, presets
from tests.test_frontend_api import client

APP = (Path(__file__).resolve().parents[1] / "ironm_agent" / "web" / "app.js").read_text()
KINDS = ("早餐", "午餐", "晚餐", "加餐", "夜宵", "练前", "练后")


def eaten(day: dict[str, Any], kind: str) -> list[str]:
    return [m["name"] for m in day["meals"] if m["kind"] == kind]


def fake(name: str, kcal: float) -> Any:
    async def estimate(llm: Any, said: str, kind: Any, image: Any = None) -> Meal:
        return Meal(
            kind=kind,
            name=name,
            items=[said],
            macros=Macros(kcal=kcal, protein_g=20, carbs_g=30, fat_g=10),
        )

    return estimate


def test_seven_meal_kinds() -> None:
    assert MEAL_KINDS == KINDS
    assert 'const MEAL_KINDS = ["早餐", "午餐", "晚餐", "加餐", "夜宵", "练前", "练后"];' in APP


def test_one_meal_per_kind_per_day(monkeypatch: pytest.MonkeyPatch) -> None:
    from ironm_agent import web_more

    c, _, _ = client(monkeypatch=monkeypatch)
    monkeypatch.setattr(web_more, "estimate", fake("包子", 300))
    first = c.post("/iron/api/meals", data={"said": "两个包子", "kind": "早餐"}).json()
    c.post("/iron/api/meals", data={"said": "一个苹果", "kind": "练后"})
    monkeypatch.setattr(web_more, "estimate", fake("燕麦牛奶", 420))
    r = c.post("/iron/api/meals", data={"said": "燕麦加牛奶", "kind": "早餐"})
    assert r.status_code == 200, r.text
    got = r.json()
    assert eaten(got, "早餐") == ["燕麦牛奶"] and got["replaced"] == ["包子"]  # 替换了原来的早餐
    assert first["meal"]["id"] not in {m["id"] for m in got["meals"]}
    assert len(eaten(got, "练后")) == 1 and got["totals"]["kcal"] == 420 + 300

    # 估算失败：原来的早餐还在
    async def broken(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(web_more, "estimate", broken)
    assert c.post("/iron/api/meals", data={"said": "又吃了点", "kind": "早餐"}).status_code == 503
    assert eaten(c.get("/iron/api/meals").json(), "早餐") == ["燕麦牛奶"]
    # 减脂餐、推荐直接记下也替换
    first_preset = presets()[0]
    after = c.post("/iron/api/meals/preset", json={"preset": first_preset.id, "kind": "早餐"})
    assert eaten(after.json(), "早餐") == [first_preset.name]
    rec = {"kind": "早餐", "name": "鸡蛋三明治", "items": ["鸡蛋", "全麦面包"],
           "macros": {"kcal": 380, "protein_g": 22, "carbs_g": 40, "fat_g": 12}}  # fmt: skip
    after = c.post("/iron/api/meals/record", json=rec).json()
    assert eaten(after, "早餐") == ["鸡蛋三明治"]
    assert c.post("/iron/api/meals", data={"said": "x", "kind": "下午茶"}).status_code == 422


def test_page_has_two_entries_and_picks_kind_after() -> None:
    page = APP[APP.index("async function food(view)") : APP.index("function meter(")]
    entry = page[page.index("function mealEntry") : page.index("function logMealSheet")]
    assert "拍" in entry and "填" in entry and "pills(" not in entry  # 入口里不先选餐次
    assert "capture" not in entry  # 不限只能用相机：手机弹出拍照或从相册选
    sheet = page[page.index("function logMealSheet") : page.index("function mealRecord")]
    assert "pills(MEAL_KINDS" in sheet and "mealKindNow()" in sheet and "记下后会替换" in sheet
    record = page[page.index("function mealRecord") :]
    assert "/iron/api/diet/review" in record and "还没记" in record
    assert "dietReviewCard()" not in page and 'section("记一餐"' not in page
