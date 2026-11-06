"""打卡分享卡和周报的接口（spec [2026-11-03] §147）。只读已有的训练、饮食、指标记录，规则算，不调用模型。"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ironm_agent import web_more
from ironm_agent.share import week_report, workout_card
from ironm_agent.training import TrainingStore, week_start
from ironm_agent.web_more import ILLNESS, MEALS, PHOTOS, TRAINING, _verify, _web, checkin_streak

_log = logging.getLogger(__name__)
HISTORY_DAYS = 365  # 算破纪录往前看多久

router = APIRouter()


@router.get("/iron/api/share/workout/{log_id}")
async def share_workout(
    log_id: str,
    user_id: str = Depends(_verify()),
    store: TrainingStore = TRAINING,
    photos: Any = PHOTOS,
) -> dict[str, Any]:
    """一次训练的分享卡；没有这条或那天没练的返回 404。"""
    today = date.today()
    rows = await store.workouts(user_id, today - timedelta(days=HISTORY_DAYS))
    hit = next((x for x in rows if x.id == log_id), None)
    if hit is None or not hit.log.done:
        raise HTTPException(404, "没有这次训练")
    days = {x.log.day for x in rows if x.log.done or x.log.rest}  # 同战绩页：练了或记了没练都算
    has_photo = False
    try:
        has_photo = log_id in await photos.having(user_id, [log_id])
    except Exception as e:
        _log.warning("share photo unavailable: error_type=%s", type(e).__name__)
    card = workout_card(hit.log, [x.log for x in rows], checkin_streak(days, hit.log.day))
    return {"id": hit.id, "photo": has_photo, **card}


@router.get("/iron/api/report/week")
async def report_week(
    user_id: str = Depends(_verify()),
    store: TrainingStore = TRAINING,
    meals: Any = MEALS,
    illness: Any = ILLNESS,
) -> dict[str, Any]:
    """上一周（上周一到周日）的周报。"""
    from ironm_agent.illness import sick_days

    monday = week_start(date.today()) - timedelta(days=7)
    sunday = monday + timedelta(days=6)
    rows = await store.workouts(user_id, monday - timedelta(days=HISTORY_DAYS))
    logs = [x.log for x in rows if x.log.day <= sunday]
    versions = await store.plans(user_id)
    current = next((v for v in reversed(versions) if v.since <= sunday), None)
    # 那周日的数据：体重、热量目标都按那天
    snap = await _web().snapshot_for(user_id, sunday)
    sick: frozenset[date] = frozenset()
    try:
        sick = sick_days(await illness.since(user_id, monday - timedelta(days=28)), sunday)
    except Exception as e:
        _log.warning("report illness unavailable: error_type=%s", type(e).__name__)
    plan = current.plan if current else None
    since = current.since if current else None
    day_kcal: dict[date, float] = {}
    try:
        for m in await meals.since(user_id, monday):
            if m.day <= sunday:
                day_kcal[m.day] = day_kcal.get(m.day, 0.0) + m.meal.macros.kcal
    except Exception as e:
        _log.warning("report meals unavailable: error_type=%s", type(e).__name__)
    target = next((m.value for m in snap.metrics if m.key == "kcal_target"), None)
    report = week_report(monday, plan, since, logs, weights=snap.readings.weight, day_kcal=day_kcal,
                         kcal_target=target, sick=sick)  # fmt: skip
    return {**report, "seen": await _seen(user_id) == monday}


async def _seen(user_id: str) -> date | None:
    """对话页的周报消息点掉的是哪一周；读不到当没点掉。"""
    try:
        state = await web_more.coach_deps().store.get(user_id)
    except Exception as e:
        _log.warning("report seen unavailable: error_type=%s", type(e).__name__)
        return None
    return state.report_seen if state is not None else None


@router.post("/iron/api/report/week/seen")
async def report_seen(user_id: str = Depends(_verify())) -> dict[str, Any]:
    """对话页的周报消息点掉了：这周不再出（§147）。"""
    from ironm_agent.coach_state import mark_report_seen

    monday = week_start(date.today()) - timedelta(days=7)
    return {"ok": await mark_report_seen(web_more.coach_deps().store, user_id, monday)}
