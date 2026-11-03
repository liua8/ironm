"""饮食（spec [2026-10-23] §118）：食物库、模型认食物代码算、改份量、常吃的、食谱、饮食计划、按实际估消耗。

不连数据库、不调用真实模型（模型的输出用假模型）。
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ironm_agent.diet_adjust import KCAL_PER_KG, Observed, observed, propose
from ironm_agent.foods import by_id, find, foods
from ironm_agent.llm import Reply
from ironm_agent.meals import Macros, Meal, MealBook, StoredMeal, estimate, food_line
from ironm_agent.metrics import KcalAdjust, Metric, Profile
from ironm_agent.recipes import DietBook, recommended, set_of
from tests.test_frontend_api import client as api_client

TODAY = date.today()


def client(
    monkeypatch: pytest.MonkeyPatch, user: str = "42", kitchen: DietBook | None = None
) -> tuple[TestClient, MealBook, DietBook]:
    from ironm_agent import web_diet

    c, _, meals = api_client(user, monkeypatch)
    kitchen = kitchen or DietBook()
    c.app.dependency_overrides[web_diet.recipe_store] = lambda: kitchen  # type: ignore[attr-defined]
    return c, meals, kitchen


class FakeLLM:
    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw, self.calls = raw, 0

    async def chat(self, stage: Any, messages: Any, **_: Any) -> Reply:
        self.calls += 1
        return Reply(json.dumps(self.raw, ensure_ascii=False))


# ---- 需求 1：食物库 ----


def test_library_is_consistent() -> None:
    fs = foods()
    assert len([f for f in fs if not f.dish]) >= 100 and len([f for f in fs if f.dish]) >= 25
    for f in fs:
        assert f.unit and f.unit_g > 0, f.name
        if f.dish:
            assert f.per100 is None and f.parts, f.name  # 菜品只写原料和油
            continue
        assert f.per100 is not None
        p = f.per100
        calc = p.protein_g * 4 + p.carbs_g * 4 + p.fat_g * 9
        if not f.alcohol:  # 碳水含膳食纤维：蔬菜按 4 千卡算会偏高
            assert abs(calc - p.kcal) <= max(0.17 * p.kcal, 10), (f.name, p.kcal, calc)
    words = [w for f in fs for w in (f.name, *f.aka)]
    assert len(words) == len(set(words))
    raw = (by_id()["rice"].per100, by_id()["oil"].per100)
    assert raw[0] is not None and raw[0].kcal == 130 and raw[1] is not None and raw[1].fat_g == 100
    from ironm_agent.foods import FOODS_PATH

    assert "review: claude_draft" in FOODS_PATH.read_text()


def test_dishes_are_computed_from_their_parts_and_oil() -> None:
    dish = find("西红柿炒鸡蛋")
    assert dish is not None and dish.name == "番茄炒蛋" and dish.unit_g == 310
    egg, tomato, oil = (by_id()[k] for k in ("egg", "tomato", "oil"))
    want = egg.nutrition(100).kcal + tomato.nutrition(200).kcal + oil.nutrition(10).kcal
    assert round(dish.nutrition(310).kcal) == round(want)
    less, more = dish.nutrition(310, "少油").kcal, dish.nutrition(310, "多油").kcal
    assert round(want - less) == round(oil.nutrition(5).kcal) and round(more - want) == round(
        oil.nutrition(5).kcal
    )
    assert find("一碗米饭") is by_id()["rice"] and find("火星菜") is None


# ---- 需求 2：模型认食物，代码查库算 ----


def test_model_names_foods_and_code_does_the_numbers() -> None:
    llm = FakeLLM({"name": "午饭", "confidence": "中", "note": "", "foods": [
        {"name": "米饭", "grams": 200, "oil": "正常", "per100": {"kcal": 999, "protein_g": 1, "carbs_g": 1, "fat_g": 1}},
        {"name": "番茄炒蛋", "grams": 310, "oil": "多油"},
        {"name": "神秘酱料", "grams": 50, "per100": {"kcal": 200, "protein_g": 2, "carbs_g": 20, "fat_g": 12}},
        {"name": "看不清的东西", "grams": 100},  # 库里没有又没给估值：跳过
        {"name": "米饭", "grams": 0},  # 克数不合理：跳过
    ]})  # fmt: skip
    meal = asyncio.run(estimate(llm, "一碗饭加番茄炒蛋", "午餐"))  # type: ignore[arg-type]
    assert meal is not None and [x.name for x in meal.foods] == ["米饭", "番茄炒蛋", "神秘酱料"]
    rice, dish, sauce = meal.foods
    assert rice.macros.kcal == 260 and rice.est100 is None  # 库里有：按库，不用模型的 999
    assert dish.oil == "多油" and dish.macros.kcal == round(
        by_id()["tomato-egg"].nutrition(310, "多油").kcal
    )
    assert sauce.macros.kcal == 100 and sauce.est100 is not None
    assert meal.macros.kcal == rice.macros.kcal + dish.macros.kcal + sauce.macros.kcal
    assert "库里没有，按估算：神秘酱料" in meal.note
    old = FakeLLM({"name": "面", "kcal": 500, "protein_g": 20, "carbs_g": 70, "fat_g": 15})
    plain = asyncio.run(estimate(old, "一碗面", "午餐"))  # type: ignore[arg-type]
    assert (
        plain is not None and plain.foods == [] and plain.macros.kcal == 500
    )  # 没给逐样食物：照旧


# ---- 需求 3：改份量、从食物库选 ----


def test_from_library_and_edit_portions_without_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from ironm_agent import web_more

    async def no_model(*_: Any, **__: Any) -> Any:
        raise AssertionError("改份量不调用模型")

    monkeypatch.setattr(web_more, "estimate", no_model)
    c, _, _ = client(monkeypatch)
    r = c.post("/iron/api/meals/foods", json={"kind": "午餐", "foods": [
        {"food_id": "rice", "grams": 150}, {"food_id": "chicken-breast", "grams": 100}]})  # fmt: skip
    assert r.status_code == 200, r.text
    meal = r.json()["meal"]
    assert meal["macros"]["kcal"] == (195 + 165) and len(meal["foods"]) == 2
    bad = c.post(
        "/iron/api/meals/foods", json={"kind": "午餐", "foods": [{"food_id": "nope", "grams": 100}]}
    )
    assert bad.status_code == 422
    lines = [{"name": "米饭", "food_id": "rice", "grams": 300},  # 改克数
             {"food_id": "tomato-egg", "grams": 155, "oil": "少油"}]  # 删了鸡胸、从库里加一样  # fmt: skip
    edited = c.put(f"/iron/api/meals/{meal['id']}", json={"foods": lines})
    assert edited.status_code == 200, edited.text
    got = edited.json()["meal"]
    egg = round(by_id()["tomato-egg"].nutrition(155, "少油").kcal)
    assert got["macros"]["kcal"] == 390 + egg and [x["name"] for x in got["foods"]] == [
        "米饭",
        "番茄炒蛋",
    ]
    assert c.put("/iron/api/meals/nope", json={"foods": lines}).status_code == 404
    other, _, _ = client(monkeypatch, user="7")
    assert other.put(f"/iron/api/meals/{meal['id']}", json={"foods": lines}).status_code == 404


def test_estimated_lines_keep_their_estimate_and_old_records_cannot_be_edited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c, meals, _ = client(monkeypatch)
    est = Macros(kcal=200, protein_g=2, carbs_g=20, fat_g=12)
    sauce = food_line("神秘酱料", 50, est100=est)
    row = asyncio.run(
        meals.add("42", TODAY, Meal(kind="晚餐", name="x", macros=sauce.macros, foods=[sauce]))
    )
    r = c.put(f"/iron/api/meals/{row.id}", json={"foods": [{"name": "神秘酱料", "grams": 100}]})
    assert r.status_code == 200 and r.json()["meal"]["macros"]["kcal"] == 200
    assert (
        c.put(
            f"/iron/api/meals/{row.id}", json={"foods": [{"name": "别的", "grams": 100}]}
        ).status_code
        == 422
    )
    old = asyncio.run(meals.add("42", TODAY, Meal(kind="早餐", name="以前的", macros=est)))
    assert (
        c.put(
            f"/iron/api/meals/{old.id}", json={"foods": [{"food_id": "rice", "grams": 100}]}
        ).status_code
        == 409
    )


def test_food_search() -> None:
    from ironm_agent.foods import search

    names = [f.name for f in search("鸡")]
    assert names[0] == "鸡蛋" and "鸡胸肉（熟）" in names and search("") == []


# ---- 需求 4：常吃的 ----


def seed(
    meals: MealBook, name: str, days_ago: list[int], kcal: float = 300, user: str = "42"
) -> None:
    for d in days_ago:
        m = Meal(
            kind="早餐", name=name, macros=Macros(kcal=kcal, protein_g=20, carbs_g=30, fat_g=10)
        )
        row = asyncio.run(meals.add(user, TODAY - timedelta(days=d), m))
        meals.rows[row.id] = (
            user,
            StoredMeal(row.id, row.day, m, datetime.now().astimezone() - timedelta(days=d)),
            None,
            "",
        )


def test_usual_is_three_times_in_two_weeks(monkeypatch: pytest.MonkeyPatch) -> None:
    c, meals, _ = client(monkeypatch)
    seed(meals, "燕麦牛奶", [1, 3, 5, 8])
    seed(meals, "包子", [1, 2])  # 只有两次
    seed(meals, "粥", [2, 15, 20])  # 两周外的不算
    got = c.get("/iron/api/meals/usual").json()["usual"]
    assert [(x["name"], x["times"]) for x in got] == [("燕麦牛奶", 4)]
    r = c.post("/iron/api/meals/usual", json={"id": got[0]["id"], "kind": "加餐"})
    assert (
        r.status_code == 200
        and r.json()["meal"]["name"] == "燕麦牛奶"
        and r.json()["meal"]["kind"] == "加餐"
    )
    assert c.post("/iron/api/meals/usual", json={"id": "nope", "kind": "加餐"}).status_code == 404


# ---- 需求 5：食谱 ----


def test_recommended_recipes_use_the_library() -> None:
    rs = recommended()
    assert len(rs) >= 20 and all(p.food_id in by_id() for r in rs for p in r.parts)
    r = next(x for x in rs if x.id == "chicken-brown-rice")
    lib = by_id()
    whole = (
        sum(lib[p.food_id].nutrition(p.grams).kcal for p in r.parts)
        + lib["oil"].nutrition(r.oil).kcal
    )
    assert r.per_serving().kcal == round(whole / r.servings)
    meal = r.meal("午餐", 0.5)
    assert meal.name == "鸡胸肉西兰花糙米饭（0.5 份）" and abs(meal.macros.kcal - whole / 4) <= len(
        meal.foods
    )


def test_my_recipes_belong_to_me_and_log_by_servings(monkeypatch: pytest.MonkeyPatch) -> None:
    c, _, kitchen = client(monkeypatch)
    body = {"name": "我的早餐", "servings": 2, "tags": ["早餐", "乱写"], "oil": 0,
            "parts": [{"food_id": "egg", "grams": 200}, {"food_id": "milk", "grams": 500}], "steps": ["煮", " "]}  # fmt: skip
    r = c.post("/iron/api/recipes", json=body).json()["recipe"]
    assert r["mine"] and r["tags"] == ["早餐"] and r["steps"] == ["煮"]
    assert abs(r["per_serving"]["kcal"] - (286 + 305) / 2) <= 1
    assert (
        c.post(
            "/iron/api/recipes", json={**body, "parts": [{"food_id": "nope", "grams": 1}]}
        ).status_code
        == 422
    )
    listed = c.get("/iron/api/recipes").json()
    assert [x["id"] for x in listed["mine"]] == [r["id"]] and len(listed["recommended"]) >= 20
    assert all(
        "减脂" in x["tags"] for x in c.get("/iron/api/recipes?tag=减脂").json()["recommended"]
    )
    logged = c.post(
        f"/iron/api/recipes/{r['id']}/log", json={"kind": "早餐", "servings": 1}
    ).json()["meal"]
    assert (
        abs(logged["macros"]["kcal"] - (286 + 305) / 2) <= 1 and logged["foods"][0]["grams"] == 100
    )
    other, _, _ = client(monkeypatch, user="7", kitchen=kitchen)
    assert other.get("/iron/api/recipes").json()["mine"] == []
    assert other.delete(f"/iron/api/recipes/{r['id']}").status_code == 404
    assert other.post(f"/iron/api/recipes/{r['id']}/log", json={"kind": "早餐"}).status_code == 404
    edited = c.put(f"/iron/api/recipes/{r['id']}", json={**body, "name": "改名"}).json()["recipe"]
    assert edited["name"] == "改名" and edited["id"] == r["id"]
    assert c.delete(f"/iron/api/recipes/{r['id']}").status_code == 200
    assert c.get("/iron/api/recipes").json()["mine"] == []


# ---- 需求 6：饮食计划 ----


def test_weekday_and_weekend_plans(monkeypatch: pytest.MonkeyPatch) -> None:
    c, meals, _ = client(monkeypatch)
    seed(meals, "燕麦牛奶", [1, 2, 3], kcal=400)
    usual = c.get("/iron/api/meals/usual").json()["usual"][0]["id"]
    today_set = set_of(TODAY)
    other = "weekend" if today_set == "weekday" else "weekday"

    def put(s: str, slot: str, ref: Any) -> Any:
        return c.put("/iron/api/diet/plan", json={"set": s, "slot": slot, "ref": ref})

    assert put(today_set, "早餐", {"type": "meal", "id": usual}).status_code == 200
    assert (
        put(
            today_set, "午餐", {"type": "recipe", "id": "chicken-brown-rice", "servings": 1}
        ).status_code
        == 200
    )
    assert put(other, "晚餐", {"type": "preset", "id": "takeout-chicken-rice"}).status_code == 200
    assert put(other, "晚餐", {"type": "preset", "id": "nope"}).status_code == 404
    got = c.get("/iron/api/diet/plan").json()
    lunch = next(r for r in recommended() if r.id == "chicken-brown-rice").per_serving().kcal
    assert (
        got["today_set"] == today_set and abs(got["totals"][today_set]["kcal"] - (400 + lunch)) <= 2
    )
    assert (
        got["target"] == {"kcal": 2000, "protein_g": 120} and got["sets"][today_set]["晚餐"] is None
    )
    assert got["sets"][other]["晚餐"]["name"] == "鸡胸肉糙米饭（少酱）"
    r = c.post("/iron/api/diet/plan/log", json={"slot": "午餐"})
    assert (
        r.status_code == 200
        and r.json()["meal"]["kind"] == "午餐"
        and r.json()["meal"]["note"] == "照计划记"
    )
    assert (
        c.post("/iron/api/diet/plan/log", json={"slot": "晚餐"}).status_code == 404
    )  # 今天这套的晚餐是空的
    assert put(today_set, "午餐", None).json()["sets"][today_set]["午餐"] is None


def test_set_of_day() -> None:
    sat = date(2026, 11, 7)
    assert set_of(sat) == "weekend" and set_of(sat + timedelta(days=2)) == "weekday"


# ---- 需求 7：按实际估消耗 ----


def days(n: int, meals: int = 3, kcal: float = 2000) -> dict[date, tuple[int, float]]:
    return {TODAY - timedelta(days=i): (meals, kcal) for i in range(n)}


def weights(n: int, per_day: float, start: float = 70) -> list[tuple[date, float]]:
    return [(TODAY - timedelta(days=i), start - per_day * i) for i in range(0, n * 2, 2)]


def test_observed_needs_enough_logging_and_weighing() -> None:
    seen, why = observed(
        days(14), weights(7, -0.05), TODAY
    )  # 每天降 0.05 公斤，一共称 7 次跨 12 天
    assert (
        seen is not None and seen.intake == 2000 and seen.tdee == round(2000 + 0.05 * KCAL_PER_KG)
    )
    assert seen.kg_per_week == -0.35
    none, why = observed(days(9), weights(7, 0), TODAY)
    assert none is None and "有 9 天，要 10 天" in why
    none, why = observed(days(14, meals=1), weights(3, 0), TODAY)
    assert none is None and "有 0 天" in why and "称了 3 次" in why


def metrics(tdee: float, target: float = 1800) -> list[Metric]:
    def m(key: str, v: float) -> Metric:
        return Metric(key, key, v, "", "")

    return [m("kcal_target", target), m("bmr", 1500), m("tdee", tdee)]


def test_observed_proposal_goes_through_the_same_limits() -> None:
    p = Profile(height_cm=175, sex="male", goal="fat_loss", activity="moderate")
    low = Observed(2000, 1800, 0.0, 12, 7)
    prop, _ = propose(metrics(2400), p, None, TODAY, low)  # 实际比公式低 400：往下调，一次最多 200
    assert prop is not None and prop.delta == -200 and "实际消耗约 2000" in prop.reason
    high = Observed(2800, 2600, 0.0, 12, 7)
    prop, _ = propose(metrics(2400), p, None, TODAY, high)
    assert prop is not None and prop.delta == 150  # 往上调一次最多 150
    near = Observed(2600, 2600, 0.0, 12, 7)  # 差 200：不按实际调，退回按体重趋势（这里没有趋势）
    prop, why = propose(metrics(2400), p, None, TODAY, near)
    assert prop is None and "体重记录还不够" in why
    cool = KcalAdjust(-200, TODAY - timedelta(days=3), "x")
    assert propose(metrics(2400), p, cool, TODAY, low)[0] is None  # 冷却期照旧
    capped = KcalAdjust(-500, TODAY - timedelta(days=30), "x")
    assert propose(metrics(2400), p, capped, TODAY, low)[0] is None  # 累计 ±500 照旧


def test_review_shows_observed_or_what_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from ironm_agent import web, web_more
    from ironm_agent.casefile import Snapshot
    from ironm_agent.diet_adjust import DietBook as AdjustBook
    from ironm_agent.metrics import Readings

    c, meals, _ = client(monkeypatch)
    adjust = AdjustBook()
    c.app.dependency_overrides[web_more.diet_store] = lambda: adjust  # type: ignore[attr-defined]
    p = Profile(height_cm=175, sex="male", goal="fat_loss", activity="moderate")

    async def snap(_: str, today: date | None = None) -> Snapshot:
        return Snapshot(p, Readings(weight=tuple(weights(7, 0.0))), tuple(metrics(2600)), TODAY)

    monkeypatch.setattr(web, "snapshot_for", snap)
    got = c.get("/iron/api/diet/review").json()
    assert got["observed"] is None and "有 0 天，要 10 天" in got["observed_lack"]
    for i in range(12):
        for kind in ("早餐", "午餐"):
            m = Meal(
                kind=kind, name="x", macros=Macros(kcal=1100, protein_g=50, carbs_g=120, fat_g=40)
            )
            asyncio.run(meals.add("42", TODAY - timedelta(days=i), m))
    got = c.get("/iron/api/diet/review").json()
    assert (
        got["observed"]["tdee"] == 2200 and got["observed"]["formula"] == 2600
    )  # 体重不变：吃的就是消耗
    assert got["proposal"]["delta"] == -200 and "实际消耗约 2200" in got["proposal"]["reason"]
    assert c.post("/iron/api/diet/adjust").json()["current"]["kcal"] == -200  # 确认走原来的调整


def test_food_page_has_the_new_parts() -> None:
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "ironm_agent" / "web" / "app.js").read_text()
    for words in ("从库里选", "常吃的", "保存份量", "照片估算通常偏低", "新建食谱", "照计划记",
                  "按你记的估的实际消耗", 'section("今天吃什么"', 'section("食谱"', "foodTile(", "imageCredit("):  # fmt: skip
        assert words in js, words
    assert (
        "0.5 : 1" not in js and "OIL_K = { 少油: 0.5, 正常: 1, 多油: 1.5 }" in js
    )  # 页面预估和服务端同一个油量算法


def test_home_coach_uses_the_same_observed_burn() -> None:
    """首页管家的提议和饮食页同一个算法（§118）：管家读到的输入里有按实际估的消耗。"""
    from dataclasses import replace

    from ironm_agent.casefile import Snapshot
    from ironm_agent.coach_state import _gather
    from ironm_agent.metrics import Readings
    from tests.test_coach import deps

    meals = MealBook()
    for i in range(12):
        for kind in ("早餐", "午餐"):
            m = Meal(
                kind=kind, name="x", macros=Macros(kcal=1100, protein_g=50, carbs_g=120, fat_g=40)
            )
            asyncio.run(meals.add("42", TODAY - timedelta(days=i), m))
    p = Profile(height_cm=175, sex="male", goal="fat_loss", activity="moderate")
    s = Snapshot(p, Readings(weight=tuple(weights(7, 0.0))), tuple(metrics(2600)), TODAY)
    d = replace(deps(snapshot=s), meals=meals)
    inp = asyncio.run(_gather("42", d, TODAY))
    assert inp.seen is not None and inp.seen.tdee == 2200
    assert asyncio.run(_gather("42", deps(snapshot=s), TODAY)).seen is None  # 没给饮食记录：不估


def test_food_images_only_with_allowed_licenses_and_fall_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """配图（§119）：清单里许可不合格、文件名不对、文件没下载的都不返回；没图时页面用色块首字。"""
    from ironm_agent import food_images

    (tmp_path / "food-images").mkdir()
    (tmp_path / "food-images" / "food-rice.jpg").write_bytes(b"x")
    (tmp_path / "food-images" / "food-egg.jpg").write_bytes(b"x")
    monkeypatch.setenv("IRONM_DATA_DIR", str(tmp_path))
    manifest = tmp_path / "food_images.yaml"
    manifest.write_text(
        "images:\n"
        "  food:rice: {file: food-rice.jpg, license: CC BY-SA 4.0, author: A, page: p}\n"
        "  food:egg: {file: food-egg.jpg, license: All rights reserved, author: B, page: p}\n"
        "  food:milk: {file: food-milk.jpg, license: CC0, author: C, page: p}\n"
        "  food:oil: {file: ../evil.jpg, license: CC0, author: D, page: p}\n"
    )
    monkeypatch.setattr(food_images, "MANIFEST", manifest)
    food_images._load.cache_clear()
    try:
        assert food_images.image_for("food:rice") == {"url": "/iron/api/food-images/food-rice.jpg", "author": "A",
                                                       "license": "CC BY-SA 4.0", "license_url": "", "page": "p"}  # fmt: skip
        assert food_images.image_for("food:egg") is None  # 许可不合格
        assert food_images.image_for("food:milk") is None  # 没下载
        assert food_images.image_for("food:oil") is None  # 文件名不对
        assert food_images.image_path("../evil.jpg") is None
        rice = food_line("", 150, food_id="rice")
        egg = food_line("", 100, food_id="egg")
        from ironm_agent.meals import meal_image

        m = Meal(kind="午餐", name="x", macros=rice.macros, foods=[egg, rice])
        assert meal_image(m)["author"] == "A"  # type: ignore[index]  # 分量最大、有图的那样
        assert meal_image(m.model_copy(update={"image_key": "recipe:none"}))["author"] == "A"  # type: ignore[index]
    finally:
        food_images._load.cache_clear()
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "ironm_agent" / "web" / "app.js").read_text()
    assert "function foodTile(" in js and "--hue" in js  # 没图：分类颜色色块 + 名字首字


def test_every_query_key_points_at_something_real() -> None:
    from ironm_agent.food_images import QUERIES
    from ironm_agent.meals import presets
    from ironm_agent.yamlfile import load_yaml

    keys = load_yaml(QUERIES)["queries"]  # type: ignore[index]
    known = (
        {f"food:{f.id}" for f in foods()}
        | {f"recipe:{r.id}" for r in recommended()}
        | {f"preset:{p.id}" for p in presets()}
    )
    assert set(keys) <= known and len(keys) == len(known)  # 每样都写了检索词、没有写错的
