"""训练记录器的接口（spec [2026-10-23] §71）：开始、保存、结束、放弃进行中的训练。
内容不进日志；结束后存成训练记录，之后和打卡一样处理。"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ironm_agent.live import (
    Live,
    LiveError,
    LiveItem,
    LiveStore,
    default_live,
    fresh,
    known,
    new_item,
    stale,
    summary,
    to_log,
)
from ironm_agent.memory_store import MemoryStore
from ironm_agent.training import TrainingStore
from ironm_agent.web import _verify, after_workout, memory_store, training_store
from ironm_agent.web_more import ILLNESS, PAIN

_log = logging.getLogger("ironm_agent.live")
router = APIRouter()


def live_store() -> LiveStore:
    return default_live()


LIVE = Depends(live_store)  # 测试时用 dependency_overrides 换成内存版
# 和打卡同一份训练记录、同一份记忆（web.py 的依赖，测试时一样能换）
TRAINING: Any = Depends(training_store)
STORE: Any = Depends(memory_store)


class StartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercises: list[str] = Field(default_factory=list, max_length=15)
    today_plan: bool = False  # 从首页开始：带上今天计划里的动作


class SaveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=32)
    items: list[LiveItem] = Field(default_factory=list, max_length=15)


class AddIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercise: str = Field(max_length=30)


class FinishIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rpe: int | None = Field(default=None, ge=1, le=10)
    note: str = Field(default="", max_length=80)


def _out(live: Live | None, now: datetime) -> dict[str, Any]:
    if live is None:
        return {"live": None}
    return {
        "live": live.model_dump(mode="json"),
        "summary": summary(live, now),
        "now": now.isoformat(),
    }


async def _context(user_id: str, store: TrainingStore) -> tuple[Any, list[Any]]:
    plan = await store.plan(user_id)
    logs = [x.log for x in await store.workouts(user_id, date.today() - timedelta(days=60))]
    return (plan.plan if plan else None), logs


async def _finish(
    user_id: str, live: Live, now: datetime, rpe: int | None, note: str,
    store: TrainingStore, memory: MemoryStore, pain: Any, illness: Any, lives: LiveStore,
) -> dict[str, Any] | None:  # fmt: skip
    log = to_log(live, live.started.date(), now, rpe, note)
    await lives.clear(user_id)
    if log is None:
        return None
    row = await store.log(user_id, log)
    await after_workout(user_id, row.log, store, memory, pain, illness)
    _log.info(
        "live finished: exercises=%d sets=%d",
        len(log.items),
        sum(len(x.done_sets) for x in log.items),
    )
    return {"id": row.id, **row.log.model_dump(mode="json"), "line": row.log.line()}


@router.get("/iron/api/live")
async def get_live(
    user_id: str = Depends(_verify()),
    lives: LiveStore = LIVE,
    store: TrainingStore = TRAINING,
    memory: MemoryStore = STORE,
    pain: Any = PAIN,
    illness: Any = ILLNESS,
) -> dict[str, Any]:
    now = datetime.now()
    live = await lives.get(user_id)
    if live is not None and stale(live, now):  # 6 小时没动：自动结束，只保存完成的组
        saved = await _finish(
            user_id, live, live.updated, None, "", store, memory, pain, illness, lives
        )
        return {"live": None, "expired": saved}
    return _out(live, now)


@router.post("/iron/api/live/start")
async def start_live(
    body: StartIn,
    user_id: str = Depends(_verify()),
    lives: LiveStore = LIVE,
    store: TrainingStore = TRAINING,
) -> dict[str, Any]:
    now = datetime.now()
    live = await lives.get(user_id)
    if live is not None and not stale(live, now):  # 已有进行中的：接着练，不另开
        return _out(live, now)
    plan, logs = await _context(user_id, store)
    rests = await lives.rests(user_id)
    session = ""
    names: list[str] = []
    try:
        names = [known(x) for x in body.exercises]
    except LiveError as err:
        raise HTTPException(422, str(err)) from None
    if body.today_plan and plan is not None and (s := plan.session_on(date.today())) is not None:
        session = s.name
        names = [x.exercise for x in s.items if _in_library(x.exercise)] + names
    items = [new_item(n, plan, logs, rests) for n in dict.fromkeys(names)][:15]
    live = fresh(session, items, now)
    await lives.save(user_id, live)
    _log.info("live started: exercises=%d", len(items))
    return _out(live, now)


def _in_library(name: str) -> bool:
    try:
        known(name)
    except LiveError:
        return False
    return True


@router.put("/iron/api/live")
async def save_live(
    body: SaveIn, user_id: str = Depends(_verify()), lives: LiveStore = LIVE
) -> dict[str, Any]:
    """每改一处都存：整份覆盖。改过组间休息秒数的动作，下次照用。"""
    now = datetime.now()
    live = await lives.get(user_id)
    if live is None or live.id != body.id:
        raise HTTPException(409, "这次训练已经结束或换了一次，请刷新")
    before = {x.exercise: x.rest for x in live.items}
    for it in body.items:
        try:
            it.exercise = known(it.exercise)
        except LiveError as err:
            raise HTTPException(422, str(err)) from None
        if it.exercise in before and it.rest != before[it.exercise]:
            await lives.set_rest(user_id, it.exercise, it.rest)
    live = live.model_copy(update={"items": body.items, "updated": now})
    await lives.save(user_id, live)
    return _out(live, now)


@router.post("/iron/api/live/items")
async def add_live_item(
    body: AddIn,
    user_id: str = Depends(_verify()),
    lives: LiveStore = LIVE,
    store: TrainingStore = TRAINING,
) -> dict[str, Any]:
    """加一个动作：和开始时一样预先填好重量、次数和休息秒数。"""
    now = datetime.now()
    live = await lives.get(user_id)
    if live is None:
        raise HTTPException(409, "还没有开始训练")
    try:
        name = known(body.exercise)
    except LiveError as err:
        raise HTTPException(422, str(err)) from None
    if len(live.items) >= 15:
        raise HTTPException(422, "一次最多 15 个动作")
    plan, logs = await _context(user_id, store)
    item = new_item(name, plan, logs, await lives.rests(user_id))
    live = live.model_copy(update={"items": [*live.items, item], "updated": now})
    await lives.save(user_id, live)
    return _out(live, now)


@router.post("/iron/api/live/finish")
async def finish_live(
    body: FinishIn,
    user_id: str = Depends(_verify()),
    lives: LiveStore = LIVE,
    store: TrainingStore = TRAINING,
    memory: MemoryStore = STORE,
    pain: Any = PAIN,
    illness: Any = ILLNESS,
) -> dict[str, Any]:
    now = datetime.now()
    live = await lives.get(user_id)
    if live is None:
        raise HTTPException(409, "没有进行中的训练")
    done = summary(live, now)
    saved = await _finish(
        user_id, live, now, body.rpe, body.note, store, memory, pain, illness, lives
    )
    return {"summary": done, "workout": saved}


@router.delete("/iron/api/live")
async def discard_live(
    user_id: str = Depends(_verify()), lives: LiveStore = LIVE
) -> dict[str, Any]:
    await lives.clear(user_id)
    return {"live": None}
