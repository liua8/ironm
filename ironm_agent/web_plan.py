"""计划页直接改的接口（spec [2026-10-23] §106）：替代动作、改一处（只改今天 / 以后都改）、恢复今天的原计划。
套用和安全检查在 plan_edit.py；以后都改存成新一版计划（和对话里确认改计划同一条路，可以撤销）。"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ironm_agent.exercises import Equipment
from ironm_agent.memory_store import MemoryStore
from ironm_agent.plan_edit import alternatives, apply_today, edit, today_session
from ironm_agent.training import Plan, PlanEdit, TrainingStore, plan_content
from ironm_agent.web import _draft_action, _verify, memory_store, training_store
from ironm_agent.web_more import DAY, coach_later, plan_change_later, today_edits

_log = logging.getLogger("ironm_agent.plan_edit")
router = APIRouter()
# 和打卡同一份训练记录、同一份记忆（web.py 的依赖，测试时一样能换）
TRAINING: Any = Depends(training_store)
STORE: Any = Depends(memory_store)


class EditIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day: int = Field(ge=1, le=7)  # 改哪天（1 是周一）
    scope: Literal["today", "always"] = "always"  # 只改今天只能改今天那天
    edit: PlanEdit


async def _limits(
    user_id: str, memory: MemoryStore
) -> tuple[frozenset[Equipment] | None, tuple[str, ...], frozenset[str]]:
    """他的器械、伤处、特殊情况（和对话里改计划用的同一份）；读不到当作不知道。"""
    from ironm_agent.casefile import injured_parts
    from ironm_agent.memory_view import Recall
    from ironm_agent.protools.movement import equipment_of
    from ironm_agent.web_live import _special

    try:
        items = Recall.of(await memory.items(user_id)).items
    except Exception as e:
        _log.warning("memory unavailable: error_type=%s", type(e).__name__)
        items = ()
    equipment = equipment_of(
        [x.content for x in items if x.category == "equipment" and x.status == "active"]
    )
    return equipment, injured_parts(items, ""), await _special(user_id, memory)


async def _plan(store: TrainingStore, user_id: str, day: int) -> Plan:
    stored = await store.plan(user_id)
    if stored is None:
        raise HTTPException(409, "还没有训练计划")
    if all(s.day != day for s in stored.plan.sessions):
        raise HTTPException(409, "这天按计划休息，没有可改的动作")
    return stored.plan


def _today_plan(plan: Plan, edits: list[PlanEdit], today: date) -> Plan:
    """只有今天那一次（已套上今天之前的改动）的计划：只改今天时在它上面改、查。"""
    s = plan.session_on(today)
    assert s is not None
    return Plan(title=plan.title, days_per_week=1, sessions=[today_session(s, edits)])


@router.get("/iron/api/plan/alternatives")
async def get_alternatives(
    day: int,
    exercise: str,
    user_id: str = Depends(_verify()),
    store: TrainingStore = TRAINING,
    memory: MemoryStore = STORE,
    days: Any = DAY,
) -> dict[str, Any]:
    plan = await _plan(store, user_id, day)
    today = date.today()
    if day == today.isoweekday():  # 今天改过的：在改过的上面找
        plan = _today_plan(plan, await today_edits(days, user_id, today), today)
    equipment, injured, special = await _limits(user_id, memory)
    logs = [x.log for x in await store.workouts(user_id, today - timedelta(days=90))]
    found = alternatives(plan, day, exercise[:30], equipment=equipment, injured=injured,
                         special=special, logs=logs)  # fmt: skip
    return {"alternatives": found}


@router.post("/iron/api/plan/edit")
async def edit_plan(
    body: EditIn,
    user_id: str = Depends(_verify()),
    store: TrainingStore = TRAINING,
    memory: MemoryStore = STORE,
    days: Any = DAY,
) -> dict[str, Any]:
    plan = await _plan(store, user_id, body.day)
    today = date.today()
    if body.scope == "today" and body.day != today.isoweekday():
        raise HTTPException(422, "只改今天只能改今天那天")
    equipment, injured, special = await _limits(user_id, memory)
    e = body.edit.model_copy(update={"line": ""})
    before = await today_edits(days, user_id, today) if body.scope == "today" else []
    base = _today_plan(plan, before, today) if body.scope == "today" else plan
    got = edit(base, body.day, [e], equipment=equipment, injured=injured, special=special)
    if not got.lines:
        raise HTTPException(409, "；".join(got.skipped) or "没有变化")
    if got.problems:
        raise HTTPException(422, "这样改有问题：" + "；".join(got.problems))
    out: dict[str, Any] = {"status": "ok", "lines": got.lines, "notes": got.notes,
                           "warnings": got.warnings}  # fmt: skip
    if body.scope == "today":
        if e.kind == "swap":  # 被换成替代动作的：存实际换上的，今天的版本重放时才对（§122 需求 9）
            had = {x.exercise for x in base.sessions[0].items}
            used = [x.exercise for x in got.plan.sessions[0].items if x.exercise not in had]
            if used and used[0] != e.to:
                e = e.model_copy(update={"to": used[0]})
        line = "；".join([*got.lines, *got.notes])[:120]
        await days.set_edits(user_id, today, [*before, e.model_copy(update={"line": line})])
        out["today"] = got.plan.sessions[0].model_dump(mode="json")
        _log.info("plan edited for today: kind=%s", e.kind)
        return out
    from ironm_agent.constraints import Context, annotate_plan

    new = annotate_plan(got.plan, Context(injuries=tuple(injured)))
    draft = await store.add_draft(
        user_id, "plan", plan_content(new, "；".join([*got.lines, *got.notes]))
    )
    done = await _draft_action(store, user_id, draft.id, "confirm")
    if body.day == today.isoweekday() and (old := await today_edits(days, user_id, today)):
        s = new.session_on(
            today
        )  # 今天只改今天的改动里，套不上新计划的去掉（管家看的"今天"跟着对）
        kept = apply_today(s, old)[1] if s is not None else []
        if len(kept) < len(old):
            await days.set_edits(user_id, today, kept)
    plan_change_later(user_id, done.get("draft") or {})  # 和确认改计划一样记进调整经历（§45）
    coach_later(user_id, "计划页改计划")
    _log.info("plan edited: kind=%s", e.kind)
    return {**out, "draft": done["draft"]}


@router.delete("/iron/api/plan/today")
async def reset_today(user_id: str = Depends(_verify()), days: Any = DAY) -> dict[str, Any]:
    """今天的改动不要了，回到原计划。"""
    await days.set_edits(user_id, date.today(), [])
    return {"status": "ok"}


# ---- 场所与器材（spec [2026-10-23] §107）-------------------------------------------------------


class GearIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    place: Literal["gym", "home", "both"]
    gear: list[Equipment] = Field(default_factory=list, max_length=8)  # 家里有的；空 = 只有自重
    custom: list[str] = Field(default_factory=list, max_length=8)  # 自己加的器材（§107 补充）


@router.get("/iron/api/gear")
async def get_gear(
    user_id: str = Depends(_verify()), memory: MemoryStore = STORE
) -> dict[str, Any]:
    from ironm_agent.gear import read

    return read(await memory.items(user_id))


@router.put("/iron/api/gear")
async def put_gear(
    body: GearIn,
    user_id: str = Depends(_verify()),
    memory: MemoryStore = STORE,
    store: TrainingStore = TRAINING,
) -> dict[str, Any]:
    """存成一条"器械与场地"记忆，之前的标成被取代（对话里记的也一样）；回给他计划里要用没有的器械的动作。"""
    from ironm_agent.gear import FORM, current, custom_ok, missing, read, sentence
    from ironm_agent.memory_store import Change, Item, new_id, now
    from ironm_agent.protools.movement import equipment_of

    if why := next((w for w in map(custom_ok, body.custom) if w), ""):
        raise HTTPException(422, why)
    old = current(await memory.items(user_id))
    text = sentence(body.place, body.gear, body.custom if body.place != "gym" else ())
    t = now()
    item = Item(id=new_id(), category="equipment", content=text, evidence=FORM,
                origin="edited", status="active", created=t, updated=t,
                supersedes=old[-1].id if old else None)  # fmt: skip
    await memory.apply(user_id, [*(Change(kind="status", id=x.id, status="superseded") for x in old),
                                 Change(kind="insert", item=item)])  # fmt: skip
    stored = await store.plan(user_id)
    lacking = missing(stored.plan if stored else None, equipment_of([text]))
    _log.info("gear saved: place=%s gear=%d lacking=%d", body.place, len(body.gear), len(lacking))
    return {**read(await memory.items(user_id)), "lacking": lacking}
