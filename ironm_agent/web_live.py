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
from ironm_agent.training import SORE_PARTS, Feeling, Plan, TrainingStore, WorkoutLog
from ironm_agent.web import _verify, after_workout, memory_store, record_sore, training_store
from ironm_agent.web_more import DAY, FEEL, ILLNESS, PAIN, body_later, review_today, today_edits

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
    energy: Feeling | None = None  # 打卡多记的状态（§105）
    slept: Feeling | None = None
    sore: list[str] = Field(default_factory=list, max_length=len(SORE_PARTS))


def ui_step(exercise: str) -> float:
    """训练中自己调的一档（§104）：哑铃每只 1 公斤，下肢 5 公斤，其余 2.5 公斤。"""
    from ironm_agent.live_adjust import step_of

    return 1.0 if "哑铃" in exercise else step_of(exercise)


def _out(live: Live | None, now: datetime) -> dict[str, Any]:
    if live is None:
        return {"live": None}
    return {
        "live": live.model_dump(mode="json"),
        "summary": summary(live, now),
        "now": now.isoformat(),
        "steps": {x.exercise: ui_step(x.exercise) for x in live.items},
    }


async def _special(user_id: str, memory: MemoryStore) -> frozenset[str]:
    """这个人的特殊情况（§95）；读不到当作没有。"""
    from ironm_agent.casefile import risks
    from ironm_agent.special import flags
    from ironm_agent.web_more import _web

    try:
        items = await memory.items(user_id)
        snap = await _web().snapshot_for(user_id)
        return flags(snap.profile, risks(snap.readings, items, date.today()), date.today())
    except Exception as e:
        _log.info("live special unavailable: error_type=%s", type(e).__name__)
        return frozenset()


async def _context(user_id: str, store: TrainingStore) -> tuple[Any, list[Any]]:
    plan = await store.plan(user_id)
    logs = [x.log for x in await store.workouts(user_id, date.today() - timedelta(days=60))]
    return (plan.plan if plan else None), logs


async def _finish(
    user_id: str, live: Live, now: datetime, rpe: int | None, note: str,
    store: TrainingStore, memory: MemoryStore, pain: Any, illness: Any, lives: LiveStore,
    state: dict[str, Any] | None = None, feel: Any = None,
) -> dict[str, Any] | None:  # fmt: skip
    log = to_log(live, live.started.date(), now, rpe, note)
    await lives.clear(user_id)
    if log is None:
        return None
    if state:  # 精力、睡眠、哪里酸（§105）
        try:
            log = WorkoutLog.model_validate({**log.model_dump(), **state})
        except ValueError:
            _log.info("live finish state dropped")
    plan, before = await _context(user_id, store)
    row = await store.log(user_id, log)
    await after_workout(user_id, row.log, store, memory, pain, illness)
    if feel is not None:
        await record_sore(feel, user_id, row.log)
    _log.info(
        "live finished: exercises=%d sets=%d",
        len(log.items),
        sum(len(x.done_sets) for x in log.items),
    )
    return {"id": row.id, **row.log.model_dump(mode="json"), "line": row.log.line(),
            "celebrate": await _celebrate(user_id, row.log, before, plan, store, illness)}  # fmt: skip


async def _celebrate(
    user_id: str, log: Any, before: list[Any], plan: Any, store: TrainingStore, illness: Any
) -> dict[str, Any]:
    """练完的卡要用的（§92）：破了的纪录、本周练之前和之后的次数（和首页战报同一套算法）。"""
    from ironm_agent.illness import sick_days
    from ironm_agent.live import records
    from ironm_agent.training import week_of
    from ironm_agent.web_more import _episodes

    today = date.today()
    try:
        sick = sick_days(await _episodes(illness, user_id, today), today)
    except Exception:
        sick = frozenset()
    stored = await store.plan(user_id)
    since = stored.since if stored else None
    was = week_of(plan, before, today, since, sick)
    now = week_of(plan, [*before, log], today, since, sick)
    return {
        "prs": records(log, before),
        "week": {"before": was.done, "done": now.done, "planned": now.planned,
                 "reached_now": bool(now.planned) and was.done < now.planned <= now.done},
    }  # fmt: skip


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
    memory: MemoryStore = STORE,
    day: Any = DAY,
) -> dict[str, Any]:
    from ironm_agent.plan_edit import with_today
    from ironm_agent.special import no_heavier

    now = datetime.now()
    live = await lives.get(user_id)
    if live is not None and not stale(live, now):  # 已有进行中的：接着练，不另开
        return _out(live, now)
    plan, logs = await _context(user_id, store)
    if body.today_plan and plan is not None:  # 临时调整（§163）、计划页"只改今天"的按改过的（§106）
        from ironm_agent.plan_layers import load as load_temps
        from ironm_agent.plan_layers import plan_on

        plan = plan_on(plan, await load_temps(store, user_id), date.today()) or plan
        plan = with_today(plan, await today_edits(day, user_id, date.today()), date.today())
        plan = await _coach_ratio(user_id, plan)
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
    live = fresh(session, items, now).model_copy(
        update={"no_heavier": no_heavier(await _special(user_id, memory))}
    )
    await lives.save(user_id, live)
    _log.info("live started: exercises=%d", len(items))
    return _out(live, now)


def _in_library(name: str) -> bool:
    try:
        known(name)
    except LiveError:
        return False
    return True


async def _coach_ratio(user_id: str, plan: Plan) -> Plan:
    """管家复盘定了今天按几成练：今天那一次换成按几成的版本，和首页的"今天"一样（复核 11-05）。"""
    from ironm_agent.today import build

    review = await review_today(user_id)
    told = review.today() if review is not None else None
    today = plan.session_on(date.today())
    if told is None or not told.value.get("ratio") or today is None:
        return plan
    scaled = build(today, scale=float(told.value["ratio"]), scale_why=told.why).session
    return plan.model_copy(update={"sessions": [scaled if x is today else x for x in plan.sessions]})


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
    feel: Any = FEEL,
) -> dict[str, Any]:
    now = datetime.now()
    live = await lives.get(user_id)
    if live is None:
        raise HTTPException(409, "没有进行中的训练")
    done = summary(live, now)
    state = body.model_dump(include={"energy", "slept", "sore"}, exclude_defaults=True)
    saved = await _finish(
        user_id, live, now, body.rpe, body.note, store, memory, pain, illness, lives, state, feel
    )
    return {"summary": done, "workout": saved}


@router.delete("/iron/api/live")
async def discard_live(
    user_id: str = Depends(_verify()), lives: LiveStore = LIVE
) -> dict[str, Any]:
    await lives.clear(user_id)
    return {"live": None}


# ---- 训练中实时调整（spec [2026-10-23] §90）-----------------------------------------------------


class AdjustIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=32)
    said: str = Field(min_length=1, max_length=100)
    item: int | None = Field(
        default=None, ge=-1, le=14
    )  # 说的是哪个动作；不写是正在练的，-1 是整次训练


async def _situation(
    user_id: str, memory: MemoryStore, illness: Any
) -> tuple[str, list[str], list[str], str, frozenset[str]]:
    """今天的身体状态、记着的伤病、在生病没有、管家今天的调整、特殊情况（§95）；读不到的当作没有。"""
    from ironm_agent.casefile import readiness, risks
    from ironm_agent.illness import active
    from ironm_agent.special import flags
    from ironm_agent.web_more import _episodes, _web

    today = date.today()
    state = ""
    try:
        items = await memory.items(user_id)
    except Exception:
        items = []
    from ironm_agent.facts import describe
    from ironm_agent.latest import current

    items = current(items)  # 被新说法遮住的旧条目不列
    injuries = [x.content + (f"（{describe(x.data)}）" if x.data.get("parts") else "")
                for x in items if x.category in ("injury", "special") and x.status == "active"]  # fmt: skip
    special: frozenset[str] = frozenset()
    try:
        snap = await _web().snapshot_for(user_id)
        state = readiness(snap.readings, "", today).line()
        special = flags(snap.profile, risks(snap.readings, items, today), today)
    except Exception as e:
        _log.info("live adjust snapshot unavailable: error_type=%s", type(e).__name__)
    try:
        sick = [e.what() for e in active(await _episodes(illness, user_id, today), today)]
    except Exception:
        sick = []
    return state, injuries, sick, await coach_today(user_id), special


async def coach_today(user_id: str) -> str:
    """管家今天复盘定的今天怎么练（§85）；读不到当作没有（测试里换掉）。"""
    from ironm_agent.web_more import coach_deps

    try:
        state = await coach_deps().store.get(user_id)
    except Exception as e:
        _log.info("live adjust coach unavailable: error_type=%s", type(e).__name__)
        return ""
    done = state.review.today() if state is not None and state.review is not None else None
    return (
        f"{done.title}（{done.why}）"
        if done is not None and state.review.day == date.today()
        else ""
    )


@router.post("/iron/api/live/adjust")
async def adjust_live(
    body: AdjustIn,
    user_id: str = Depends(_verify()),
    lives: LiveStore = LIVE,
    store: TrainingStore = TRAINING,
    memory: MemoryStore = STORE,
    pain: Any = PAIN,
    illness: Any = ILLNESS,
) -> dict[str, Any]:
    """练的时候跟管家说一句（太重、很累、哪里疼）：模型决定后面怎么练，代码按安全底线套上并保存。"""
    from ironm_agent import spoken
    from ironm_agent.live_adjust import adjust, context_lines, current
    from ironm_agent.triggers import pain_parts

    now = datetime.now()
    live = await lives.get(user_id)
    if live is None or live.id != body.id:
        raise HTTPException(409, "这次训练已经结束或换了一次，请刷新")
    target = current(live) if body.item is None else (None if body.item == -1 else body.item)
    if target is not None and target >= len(live.items):
        raise HTTPException(422, "没有这个动作")
    plan, logs = await _context(user_id, store)
    state, injuries, sick, coach, special = await _situation(user_id, memory, illness)
    from ironm_agent.special import rules_text

    facts = context_lines(live, target, body.said, state=state, injuries=injuries, illness=sick,
                          coach=coach, logs=logs)  # fmt: skip
    if rule := rules_text(special):
        facts += "\n" + rule
    got = await adjust(spoken.default_llm(), live, body.said, target, facts, plan=plan, logs=logs,
                       rests=await lives.rests(user_id), special=special)  # fmt: skip
    if got.kinds:
        live = got.live.model_copy(update={"updated": now})
        await lives.save(user_id, live)
    if pain_parts(body.said):  # 安全护栏：这次说过疼，后面不加重（§104）
        live = live.model_copy(update={"no_heavier": True, "updated": now})
        await lives.save(user_id, live)
    body_later(user_id, body.said, date.today(), "训练中")  # 疼在哪、哪个动作由管家读出来再记（§163）
    _log.info("live adjusted: kinds=%s dropped=%d urgent=%s",
              ",".join(got.kinds) or "-", got.dropped, got.urgent)  # fmt: skip
    return {**_out(live, now), "say": got.say, "end": got.end, "urgent": got.urgent,
            "changed": len(got.kinds)}  # fmt: skip
