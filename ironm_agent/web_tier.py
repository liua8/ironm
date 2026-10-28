"""夯榜的接口（spec [2026-10-23] §60）：读一个类别的榜、给条目选档、自己添加和删除条目、最近常吃的食物。"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ironm_agent.exercise_images import images_for
from ironm_agent.meals import MealStore
from ironm_agent.tier import (
    TierError,
    TierStore,
    add_item,
    board,
    default_tier,
    frequent_foods,
    remove_item,
    set_tier,
)
from ironm_agent.web_more import MEALS, _verify

_log = logging.getLogger("ironm_agent.tier")
FOOD_DAYS = 30


def tier_store() -> TierStore:
    return default_tier()


TIER = Depends(tier_store)  # 测试时用 dependency_overrides 换成内存版
router = APIRouter()


class TierIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(max_length=20)
    key: str = Field(max_length=60)
    tier: str = Field(default="", max_length=10)


class ItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(max_length=20)
    name: str = Field(max_length=200)


async def _board(store: TierStore, user_id: str, category: str) -> dict[str, Any]:
    got = await board(store, user_id, category)
    if category.startswith("move:"):
        for x in got["items"]:
            imgs = images_for(x["key"])
            x["image"] = imgs[0]["url"] if imgs else None
    return got


def _bad(err: TierError) -> HTTPException:
    return HTTPException(422, str(err))


@router.get("/iron/api/tier")
async def get_tier(
    category: str, user_id: str = Depends(_verify()), store: TierStore = TIER
) -> dict[str, Any]:
    try:
        return await _board(store, user_id, category)
    except TierError as err:
        raise _bad(err) from None


@router.put("/iron/api/tier")
async def put_tier(
    body: TierIn, user_id: str = Depends(_verify()), store: TierStore = TIER
) -> dict[str, Any]:
    try:
        await set_tier(store, user_id, body.category, body.key, body.tier)
        return await _board(store, user_id, body.category)
    except TierError as err:
        raise _bad(err) from None


@router.post("/iron/api/tier/items")
async def post_item(
    body: ItemIn, user_id: str = Depends(_verify()), store: TierStore = TIER
) -> dict[str, Any]:
    try:
        key = await add_item(store, user_id, body.category, body.name)
        _log.info("tier item added: category=%s", body.category)
        return {"key": key, **await _board(store, user_id, body.category)}
    except TierError as err:
        raise _bad(err) from None


@router.delete("/iron/api/tier/items")
async def delete_item(
    category: str, key: str, user_id: str = Depends(_verify()), store: TierStore = TIER
) -> dict[str, Any]:
    try:
        await remove_item(store, user_id, category, key)
        return await _board(store, user_id, category)
    except TierError as err:
        raise _bad(err) from None


@router.get("/iron/api/tier/food-suggest")
async def food_suggest(
    user_id: str = Depends(_verify()), store: TierStore = TIER, meals: MealStore = MEALS
) -> dict[str, Any]:
    """最近 30 天饮食记录里常吃的，去掉食物榜里已经有的。"""
    today = date.today()
    names: list[str] = []
    for i in range(FOOD_DAYS):
        names += [m.meal.name for m in await meals.day(user_id, today - timedelta(days=i))]
    have = {r.key for r in await store.rows(user_id, "food")}
    return {"names": frequent_foods(names, have), "days": FOOD_DAYS}
