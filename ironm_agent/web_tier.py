"""夯拉榜的接口（spec [2026-10-23] §60、§66）：读一个类别的榜、投票（改票、撤回）、添加条目、举报、
最近常吃的食物。返回里没有投票人和添加人；日志只写类别。"""

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
    report_item,
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
    key: str = Field(max_length=80)
    tier: str = Field(default="", max_length=10)


class ItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(max_length=20)
    name: str = Field(max_length=200)
    force: bool = False  # 有相似的条目时，确认"不是这些"再新建


class ReportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(max_length=20)
    key: str = Field(max_length=80)


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
        got = await add_item(store, user_id, body.category, body.name, date.today(), body.force)
        _log.info("tier item added: category=%s similar=%d", body.category, len(got["similar"]))
        return got | await _board(store, user_id, body.category)
    except TierError as err:
        raise _bad(err) from None


@router.post("/iron/api/tier/report")
async def post_report(
    body: ReportIn, user_id: str = Depends(_verify()), store: TierStore = TIER
) -> dict[str, Any]:
    try:
        await report_item(store, user_id, body.category, body.key)
        _log.info("tier item reported: category=%s", body.category)
        return await _board(store, user_id, body.category)
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
    have = {x.key for x in await store.items("food")}
    return {"names": frequent_foods(names, have), "days": FOOD_DAYS}
