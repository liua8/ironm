"""饮食方案库的接口（spec [2026-11-06] §184 需求 4）：看方案、按热量目标预览份数、套用成他的饮食计划、撤销一次。

套用时先把现在的饮食计划存一份（plan_backup），再写进方案里的工作日、周末四顿；撤销把存的那份放回去，只能撤销一次。
都按食物库算，不调用模型；日志只记方案编号，不记吃了什么。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ironm_agent.diet_library import (
    SET_NAMES,
    SETS,
    DietPlan,
    by_id,
    day_meals,
    day_total,
    goal_names,
    library,
    per_day,
    plain,
    ref_names,
    scaled,
)
from ironm_agent.meals import Macros, MealStore
from ironm_agent.recipes import SLOTS, DietStore, SlotRef
from ironm_agent.web import _verify
from ironm_agent.web_diet import KITCHEN, _slot_json, get_diet_plan
from ironm_agent.web_more import MEALS

_log = logging.getLogger("ironm_agent.diet_library")
router: APIRouter = APIRouter()
BACKUP = "plan_backup"


def _macros(m: Macros) -> dict[str, float]:
    return {"kcal": round(m.kcal), "protein_g": round(m.protein_g), "carbs_g": round(m.carbs_g),
            "fat_g": round(m.fat_g)}  # fmt: skip


async def _target(user_id: str) -> Macros | None:
    """热量目标：和饮食计划同一份（web_more._targets）；算不出来时不缩放。"""
    from ironm_agent.web_more import _targets

    try:
        return (await _targets(user_id))[0]
    except Exception as e:
        _log.warning("diet library target unavailable: error_type=%s", type(e).__name__)
        return None


def _days(p: DietPlan, kcal: float | None) -> dict[str, Any]:
    """工作日、周末各四顿（kcal 为空时按推荐份数）和一天合计。"""
    out: dict[str, Any] = {}
    for s in SETS:
        servings = scaled(p, s, kcal)
        meals = day_meals(p, s, servings)
        slots = {
            k: _slot_json(
                SlotRef(type=p.days[s][k].type, id=p.days[s][k].id, servings=servings[k]), meals[k]
            )
            for k in SLOTS
        }
        out[s] = {"slots": slots, "total": _macros(day_total(meals))}
    return out


def _brief(p: DietPlan) -> dict[str, Any]:
    days = per_day(p)
    return {
        "id": p.id,
        "name": p.name,
        "goals": goal_names(p),
        "suits": [plain(x) for x in p.suits],
        "summary": plain(p.summary),
        "per_day": {
            s: {"kcal": round(days[s].kcal), "protein_g": round(days[s].protein_g)} for s in SETS
        },
    }


def _found(plan_id: str) -> DietPlan:
    p = by_id(plan_id)
    if p is None:
        raise HTTPException(404, "饮食方案库里没有这份方案")
    return p


@router.get("/iron/api/diet/library")
async def list_library(user_id: str = Depends(_verify())) -> dict[str, Any]:
    return {
        "plans": [_brief(p) for p in library()],
        "note": "每天的热量和蛋白质按推荐份数算；套用时按你的热量目标缩放。营养按食物库算（内容待审定）。",
    }


@router.get("/iron/api/diet/library/{plan_id}")
async def get_library_plan(plan_id: str, user_id: str = Depends(_verify())) -> dict[str, Any]:
    p = _found(plan_id)
    target = await _target(user_id)
    return {
        **_brief(p),
        "not_for": [plain(x) for x in p.not_for],
        "energy": plain(p.energy),
        "macros": {k: plain(getattr(p.macros, k)) for k in ("protein", "carbs", "fat")},
        "points": [plain(x) for x in p.points],
        "refs": ref_names(p),  # 资料名，不带编号（§14）
        "days": _days(p, None),
        "scaled": {
            "target": {"kcal": round(target.kcal), "protein_g": round(target.protein_g)}
            if target
            else None,
            "days": _days(p, target.kcal if target else None),
        },
        "note": "每顿 0.5–3 份、取半份的倍数；外卖和食堂的那几顿是一整份，不缩放。营养按食物库算（内容待审定）。",
    }


def plan_raw(p: DietPlan, kcal: float | None) -> dict[str, Any]:
    """按热量目标算好每顿几份，写成饮食计划的样子（工作日、周末各四顿）。"""
    raw: dict[str, Any] = {}
    for s in SETS:
        servings = scaled(p, s, kcal)
        raw[s] = {k: SlotRef(type=p.days[s][k].type, id=p.days[s][k].id, servings=servings[k]).model_dump(mode="json")
                  for k in SLOTS}  # fmt: skip
    return raw


async def apply_raw(user_id: str, raw: dict[str, Any], store: DietStore, *, applied: str, name: str,
                    draft: str = "") -> None:  # fmt: skip
    """换成这份计划：先存现在的（存不上就不换），再写新的。draft 是对话里那张卡片（撤销时核对，§190）；
    applied 是方案库编号，按他情况排的写 custom（§192）。"""
    current = await store.get(user_id, "plan", "plan") or {}
    await store.put(user_id, "plan", BACKUP, {"plan": current, "applied": applied, "name": name, "draft": draft})
    await store.put(user_id, "plan", "plan", raw)
    _log.info("diet plan applied: plan=%s card=%s", applied, bool(draft))


async def apply_plan(user_id: str, p: DietPlan, store: DietStore, kcal: float | None, draft: str = "") -> None:
    """换成方案库里这份：按热量目标算好份数再换。"""
    await apply_raw(user_id, plan_raw(p, kcal), store, applied=p.id, name=p.name, draft=draft)


async def restore_plan(user_id: str, store: DietStore, draft: str = "") -> bool:
    """放回换之前的计划，只能一次；给了 draft 时只撤销那张卡片换的（之后又换过就不撤）。"""
    backup = await store.get(user_id, "plan", BACKUP)
    if backup is None or (draft and backup.get("draft") != draft):
        return False
    await store.put(user_id, "plan", "plan", backup.get("plan") or {})
    await store.delete(user_id, "plan", BACKUP)
    _log.info("diet library undone")
    return True


async def applied_name(user_id: str, store: DietStore) -> str:
    """最近换上、还没撤销的那份叫什么（档案里写名字用，§190、§192）；没有时为空。"""
    backup = await store.get(user_id, "plan", BACKUP)
    if not backup:
        return ""
    p = by_id(str(backup.get("applied") or ""))
    return str(backup.get("name") or (p.name if p is not None else ""))


def preview_lines(p: DietPlan, kcal: float | None) -> list[str]:
    """换饮食方案卡片上的几行：工作日、周末各吃什么、一天合计（§190）。"""
    out = []
    for s in SETS:
        meals = day_meals(p, s, scaled(p, s, kcal))
        tot = day_total(meals)
        names = "、".join(f"{k}{m.name}" for k, m in meals.items())
        out.append(f"{SET_NAMES[s]}：{names}；一天约 {round(tot.kcal)} 千卡、蛋白质 {round(tot.protein_g)} 克")
    return out


@router.post("/iron/api/diet/library/undo")
async def undo_library(
    user_id: str = Depends(_verify()), store: DietStore = KITCHEN, meals: MealStore = MEALS
) -> dict[str, Any]:
    """把套用前的饮食计划放回去；只能撤销一次。"""
    if not await restore_plan(user_id, store):
        raise HTTPException(404, "没有可以撤销的饮食计划：还没套用过方案，或者已经撤销过了")
    return {**(await get_diet_plan(user_id, store, meals)), "undone": True}


@router.post("/iron/api/diet/library/{plan_id}/apply")
async def apply_library(
    plan_id: str,
    user_id: str = Depends(_verify()),
    store: DietStore = KITCHEN,
    meals: MealStore = MEALS,
) -> dict[str, Any]:
    """用这份当他的饮食计划：先存现在的，再按他的热量目标写进工作日、周末四顿。"""
    p = _found(plan_id)
    target = await _target(user_id)
    await apply_plan(user_id, p, store, target.kcal if target else None)
    return {**(await get_diet_plan(user_id, store, meals)), "applied": {"id": p.id, "name": p.name}}
