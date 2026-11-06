"""饮食的接口（spec [2026-10-23] §118）：食物库、从库里记一餐、改份量、常吃的。

都按食物库算，不调用模型；记一餐照旧每种餐每天留一份（§43）。日志不记吃了什么。
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ironm_agent.food_images import image_for
from ironm_agent.foods import Food, by_id, search
from ironm_agent.meals import FoodLine, Meal, MealStore, food_line, meal_from, meal_image
from ironm_agent.recipes import (
    MAX_PARTS,
    SLOTS,
    TAGS,
    DietStore,
    Part,
    PlanSet,
    Recipe,
    SlotRef,
    check_parts,
    my_recipes,
    new_id,
    recommended,
    set_of,
)
from ironm_agent.web import _verify
from ironm_agent.web_more import KITCHEN, MEALS, _day, _kind, _save_meal, recipe_store  # noqa: F401

_log = logging.getLogger("ironm_agent.diet")
router: APIRouter = APIRouter()
USUAL_DAYS = 14  # 最近两周
USUAL_TIMES = 3  # 记过 3 次以上算常吃的


def food_json(f: Food) -> dict[str, Any]:
    p = f.per_100()
    return {
        "id": f.id, "name": f.name, "cat": f.cat, "dish": f.dish, "unit": f.unit, "unit_g": f.unit_g,
        "oil_g": f.oil,  # 菜品一份（unit_g）里正常用多少油：页面按油量预估用
        "image": image_for(f"food:{f.id}"),
        "per100": {"kcal": round(p.kcal), "protein_g": round(p.protein_g, 1),
                   "carbs_g": round(p.carbs_g, 1), "fat_g": round(p.fat_g, 1)},
    }  # fmt: skip


@router.get("/iron/api/foods")
async def get_foods(q: str = "", user_id: str = Depends(_verify())) -> dict[str, Any]:
    return {"foods": [food_json(f) for f in search(q[:20])]}


class LineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="", max_length=30)
    food_id: str | None = Field(default=None, max_length=40)
    grams: float = Field(gt=0, le=3000)
    oil: Literal["少油", "正常", "多油"] = "正常"


class FromFoodsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = "午餐"
    name: str = Field(default="", max_length=40)
    foods: list[LineIn] = Field(min_length=1, max_length=12)


def _from_lib(x: LineIn) -> FoodLine:
    if not x.food_id or x.food_id not in by_id():
        raise HTTPException(422, f"食物库里没有「{x.name or x.food_id}」")
    return food_line(x.name, x.grams, x.oil, food_id=x.food_id)


@router.post("/iron/api/meals/foods")
async def add_from_foods(
    body: FromFoodsIn, user_id: str = Depends(_verify()), store: MealStore = MEALS
) -> dict[str, Any]:
    """不拍不写，直接从食物库选着记一餐（§118 需求 3）。"""
    lines = [_from_lib(x) for x in body.foods]
    name = body.name.strip() or "、".join(re.sub(r"[（(].*?[)）]", "", x.name) for x in lines)[:40]
    meal = meal_from(_kind(body.kind), name, lines, estimated=False, note="按食物库算")
    return await _save_meal(store, user_id, meal)


class EditIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day: str = ""
    foods: list[LineIn] = Field(min_length=1, max_length=12)


@router.put("/iron/api/meals/{meal_id}")
async def edit_meal(
    meal_id: str, body: EditIn, user_id: str = Depends(_verify()), store: MealStore = MEALS
) -> dict[str, Any]:
    """改份量（§118 需求 3）：改克数、油量，删一样、从库里加一样，按库重算；库里没有的那样沿用原来的估值。"""
    day = _day(body.day)
    found = next((m for m in await store.day(user_id, day) if m.id == meal_id), None)
    if found is None:
        raise HTTPException(404, "这条记录不存在")
    if not found.meal.foods:
        raise HTTPException(409, "这条是以前记的，没有逐样食物，不能改份量")
    had = {x.name: x for x in found.meal.foods}
    lines = []
    for x in body.foods:
        if x.food_id:
            lines.append(_from_lib(x))
        elif x.name in had and had[x.name].est100 is not None:
            lines.append(food_line(x.name, x.grams, x.oil, est100=had[x.name].est100))
        elif x.name in had and had[x.name].food_id:
            lines.append(food_line(x.name, x.grams, x.oil, food_id=had[x.name].food_id))
        else:
            raise HTTPException(422, f"食物库里没有「{x.name}」")
    old = found.meal
    meal = meal_from(old.kind, old.name, lines, estimated=old.estimated, confidence=old.confidence,
                     said=old.said, note="改过份量")  # fmt: skip
    row = await store.replace(user_id, meal_id, meal)
    if row is None:
        raise HTTPException(404, "这条记录不存在")
    _log.info("meal portions edited: lines=%d", len(lines))
    from ironm_agent.web_more import _day_json, coach_later

    coach_later(user_id, "记饮食")
    return {"meal": row.json(), **(await _day_json(user_id, day, store))}


async def usual_meals(store: MealStore, user_id: str, today: date) -> list[Any]:
    """最近 14 天里同名记过 3 次以上的，每个名字取最近的那次，次数多的在前。"""
    rows = await store.since(user_id, today - timedelta(days=USUAL_DAYS - 1))
    times = Counter(r.meal.name for r in rows)
    latest = {r.meal.name: r for r in rows}  # 按时间排好的：后面的覆盖前面的
    names = sorted((n for n, k in times.items() if k >= USUAL_TIMES), key=lambda n: -times[n])
    return [(latest[n], times[n]) for n in names]


@router.get("/iron/api/meals/usual")
async def get_usual(user_id: str = Depends(_verify()), store: MealStore = MEALS) -> dict[str, Any]:
    found = await usual_meals(store, user_id, date.today())
    return {
        "usual": [
            {"id": r.id, "name": r.meal.name, "times": k, "kind": r.meal.kind,
             "kcal": r.meal.macros.kcal, "protein_g": r.meal.macros.protein_g,
             "image": meal_image(r.meal)}
            for r, k in found
        ]
    }  # fmt: skip


class UsualIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=40)
    kind: str = "午餐"


@router.post("/iron/api/meals/usual")
async def add_usual(
    body: UsualIn, user_id: str = Depends(_verify()), store: MealStore = MEALS
) -> dict[str, Any]:
    """常吃的一键记（§118 需求 4）：照上次的食物和份量记成这一餐，不调用模型。"""
    found = next(
        (r for r, _ in await usual_meals(store, user_id, date.today()) if r.id == body.id), None
    )
    if found is None:
        raise HTTPException(404, "没有这条常吃的")
    meal = found.meal.model_copy(
        update={"kind": _kind(body.kind), "said": "", "note": "照上次记的"}
    )
    return await _save_meal(store, user_id, meal)


# ---- 食谱（§118 需求 5）--------------------------------------------------------------------------


# recipe_store、KITCHEN 挪到 web_more（换饮食方案的卡片确认时也要用，§190），这里照旧能引用


class RecipeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=20)
    tags: list[str] = Field(default_factory=list, max_length=4)
    servings: int = Field(default=1, ge=1, le=10)
    parts: list[Part] = Field(min_length=1, max_length=MAX_PARTS)
    oil: float = Field(default=0, ge=0, le=200)
    steps: list[str] = Field(default_factory=list, max_length=6)


def _recipe(body: RecipeIn, rid: str) -> Recipe:
    try:
        check_parts(body.parts)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    steps = [s.strip()[:60] for s in body.steps if s.strip()]
    tags = [t for t in body.tags if t in TAGS]
    return Recipe(id=rid, name=body.name.strip(), tags=tags, servings=body.servings,
                  parts=body.parts, oil=body.oil, steps=steps, mine=True)  # fmt: skip


async def find_recipe(store: DietStore, user_id: str, rid: str) -> Recipe | None:
    found = next((r for r in recommended() if r.id == rid), None)
    return found or next((r for r in await my_recipes(store, user_id) if r.id == rid), None)


@router.get("/iron/api/recipes")
async def get_recipes(
    tag: str = "", user_id: str = Depends(_verify()), store: DietStore = KITCHEN
) -> dict[str, Any]:
    rec = [r for r in recommended() if not tag or tag in r.tags]
    return {
        "tags": list(TAGS),
        "recommended": [r.shown() for r in rec],
        "mine": [r.shown() for r in await my_recipes(store, user_id)],
        "note": "营养按食物库算（内容待审定），实际随做法和分量变化",
    }


@router.post("/iron/api/recipes")
async def add_recipe(
    body: RecipeIn, user_id: str = Depends(_verify()), store: DietStore = KITCHEN
) -> dict[str, Any]:
    r = _recipe(body, new_id())
    await store.put(user_id, "recipe", r.id, r.model_dump(mode="json"))
    _log.info("recipe added: parts=%d", len(r.parts))
    return {"recipe": r.shown()}


@router.put("/iron/api/recipes/{rid}")
async def edit_recipe(
    rid: str, body: RecipeIn, user_id: str = Depends(_verify()), store: DietStore = KITCHEN
) -> dict[str, Any]:
    if await store.get(user_id, "recipe", rid) is None:
        raise HTTPException(404, "没有这个食谱")
    r = _recipe(body, rid)
    await store.put(user_id, "recipe", rid, r.model_dump(mode="json"))
    return {"recipe": r.shown()}


@router.delete("/iron/api/recipes/{rid}")
async def delete_recipe(
    rid: str, user_id: str = Depends(_verify()), store: DietStore = KITCHEN
) -> dict[str, Any]:
    if not await store.delete(user_id, "recipe", rid):
        raise HTTPException(404, "没有这个食谱")
    return {"deleted": rid}


class LogRecipeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = "午餐"
    servings: float = Field(default=1, ge=0.5, le=3)


@router.post("/iron/api/recipes/{rid}/log")
async def log_recipe(
    rid: str,
    body: LogRecipeIn,
    user_id: str = Depends(_verify()),
    store: DietStore = KITCHEN,
    meals: MealStore = MEALS,
) -> dict[str, Any]:
    """食谱记成这一餐：吃了几份，每样原料按比例，不调用模型。"""
    r = await find_recipe(store, user_id, rid)
    if r is None:
        raise HTTPException(404, "没有这个食谱")
    return await _save_meal(meals, user_id, r.meal(_kind(body.kind), body.servings))


# ---- 饮食计划（§118 需求 6）-----------------------------------------------------------------------


async def _slot_meal(
    store: DietStore, meals: MealStore, user_id: str, ref: SlotRef, kind: Any
) -> Meal | None:
    """计划里一个位置对应的那一餐；食谱删了、减脂餐下架了时返回 None。"""
    from ironm_agent.meals import preset_meal, presets

    if ref.type in ("recipe", "mine"):
        r = await find_recipe(store, user_id, ref.id)
        return r.meal(kind, ref.servings) if r else None
    if ref.type == "preset":
        p = next((x for x in presets() if x.id == ref.id), None)
        return preset_meal(p, kind) if p else None
    try:
        return Meal.model_validate({**(ref.snapshot or {}), "kind": kind})
    except ValidationError:
        return None


def _slot_json(ref: SlotRef | None, meal: Meal | None) -> dict[str, Any] | None:
    if ref is None:
        return None
    return {"type": ref.type, "id": ref.id, "servings": ref.servings, "missing": meal is None,
            "name": meal.name if meal else "（已经没有了）",
            "kcal": meal.macros.kcal if meal else 0, "protein_g": meal.macros.protein_g if meal else 0,
            "carbs_g": meal.macros.carbs_g if meal else 0, "fat_g": meal.macros.fat_g if meal else 0,
            # 逐样吃什么、多少克、多少千卡：首页·干饭列数量用（§125）
            "foods": [{"name": f.name, "grams": f.grams, "kcal": f.macros.kcal} for f in meal.foods] if meal else [],
            "image": meal_image(meal) if meal else None}  # fmt: skip


async def _plan(store: DietStore, user_id: str) -> dict[str, dict[str, SlotRef | None]]:
    raw = await store.get(user_id, "plan", "plan") or {}
    out: dict[str, dict[str, SlotRef | None]] = {}
    for s in ("weekday", "weekend"):
        out[s] = {}
        for slot in SLOTS:
            v = (raw.get(s) or {}).get(slot)
            try:
                out[s][slot] = SlotRef.model_validate(v) if v else None
            except ValidationError:
                out[s][slot] = None
    return out


async def plan_days(
    store: DietStore, meals: MealStore, user_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """工作日、周末每顿吃什么，和一天合计的热量、蛋白质（饮食页和管家的档案用同一份，§190）。"""
    plan = await _plan(store, user_id)
    sets: dict[str, Any] = {}
    totals: dict[str, Any] = {}
    for s, slots in plan.items():
        got = {
            k: (ref, await _slot_meal(store, meals, user_id, ref, k) if ref else None)
            for k, ref in slots.items()
        }
        sets[s] = {k: _slot_json(ref, m) for k, (ref, m) in got.items()}
        ms = [m for _, m in got.values() if m is not None]
        totals[s] = {"kcal": round(sum(m.macros.kcal for m in ms)),
                     "protein_g": round(sum(m.macros.protein_g for m in ms))}  # fmt: skip
    return sets, totals


@router.get("/iron/api/diet/plan")
async def get_diet_plan(
    user_id: str = Depends(_verify()), store: DietStore = KITCHEN, meals: MealStore = MEALS
) -> dict[str, Any]:
    from ironm_agent.web_more import _targets

    sets, totals = await plan_days(store, meals, user_id)
    try:
        target = (await _targets(user_id))[0]
    except Exception as e:
        _log.warning("diet plan target unavailable: error_type=%s", type(e).__name__)
        target = None
    return {
        "slots": list(SLOTS),
        "sets": sets,
        "totals": totals,
        "target": {"kcal": round(target.kcal), "protein_g": round(target.protein_g)}
        if target
        else None,
        "today_set": set_of(date.today()),
    }


class PlanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    set: PlanSet
    slot: Literal["早餐", "午餐", "晚餐", "加餐"]
    ref: SlotRef | None = None


@router.put("/iron/api/diet/plan")
async def put_diet_plan(
    body: PlanIn,
    user_id: str = Depends(_verify()),
    store: DietStore = KITCHEN,
    meals: MealStore = MEALS,
) -> dict[str, Any]:
    """放一个位置（或清空）：食谱、减脂餐要存在；常吃的存一份当时那一餐。"""
    ref = body.ref
    if ref is not None and ref.type == "meal":
        found = next(
            (r for r, _ in await usual_meals(meals, user_id, date.today()) if r.id == ref.id), None
        )
        if found is None:
            raise HTTPException(404, "没有这条常吃的")
        ref = ref.model_copy(update={"snapshot": found.meal.model_dump(mode="json"), "servings": 1})
    elif ref is not None and await _slot_meal(store, meals, user_id, ref, body.slot) is None:
        raise HTTPException(404, "没有这个食谱或减脂餐")
    raw = await store.get(user_id, "plan", "plan") or {}
    raw.setdefault(body.set, {})[body.slot] = ref.model_dump(mode="json") if ref else None
    await store.put(user_id, "plan", "plan", raw)
    return await get_diet_plan(user_id, store, meals)


class PlanLogIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot: Literal["早餐", "午餐", "晚餐", "加餐"]


@router.post("/iron/api/diet/plan/log")
async def log_diet_plan(
    body: PlanLogIn,
    user_id: str = Depends(_verify()),
    store: DietStore = KITCHEN,
    meals: MealStore = MEALS,
) -> dict[str, Any]:
    """照计划记：今天是工作日还是周末，取对应那套的这个位置。"""
    ref = (await _plan(store, user_id))[set_of(date.today())][body.slot]
    meal = await _slot_meal(store, meals, user_id, ref, body.slot) if ref else None
    if meal is None:
        raise HTTPException(404, "计划里这一餐是空的")
    return await _save_meal(meals, user_id, meal.model_copy(update={"note": "照计划记"}))


@router.get("/iron/api/train-images")
async def get_train_images(user_id: str = Depends(_verify())) -> dict[str, Any]:
    """每个部位的训练照片和署名（§131）：首页"今日委托"的大图。"""
    from ironm_agent.food_images import train_images

    return {"images": train_images()}


@router.get("/iron/api/food-images/{name}")
async def get_food_image(name: str) -> Any:
    """饮食和训练配图（§119、§131）：公开内容（Wikimedia Commons、Unsplash、Pexels，许可允许再用），<img> 带不了登录凭证，不验证登录。"""
    from fastapi.responses import FileResponse

    from ironm_agent.food_images import image_path

    p = image_path(name)
    if p is None:
        raise HTTPException(404, "没有这张图")
    return FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})
