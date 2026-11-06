"""iron-m 的页面与接口，挂在 mirobody 同一个服务上（/iron/），登录沿用 mirobody 的令牌。"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from ironm_agent import imports, weather
from ironm_agent import profile as profiles
from ironm_agent.brief import cheer, hero_line, today_brief, weekly_review
from ironm_agent.casefile import Snapshot, risks
from ironm_agent.exercise_images import gif_for, images_for
from ironm_agent.exercises import EQUIPMENT, NOTE, PARTS, library
from ironm_agent.healthdata import read_all
from ironm_agent.illness import active as illness_active
from ironm_agent.illness import doctor, due, question, sick_days
from ironm_agent.illness import recent as recent_illness
from ironm_agent.memory_extract import MAX_CONTENT
from ironm_agent.memory_prefs import refresh as refresh_prefs
from ironm_agent.memory_store import CATEGORIES, ORIGINS, Item, MemoryStore, default_store
from ironm_agent.memory_view import expired
from ironm_agent.metrics import ACTIVITY, GOALS, KcalAdjust, Metric, compute_all
from ironm_agent.progression import targets
from ironm_agent.training import (
    SORE_PARTS,
    Feeling,
    LogItem,
    RestWhy,
    TrainingStore,
    WorkoutLog,
    default_training,
)
from ironm_agent.web_more import (
    FEEL,
    GOAL,
    ILLNESS,
    KITCHEN,
    PAIN,
    PHOTOS,
    coach_later,
    plan_change_later,
)

_log = logging.getLogger("ironm_agent.web")

WEB_DIR = Path(__file__).with_name("web")


def _verify() -> Any:
    from mirobody.server.auth import verify_token

    return verify_token


router = APIRouter()


def metric_json(m: Metric) -> dict[str, Any]:
    out = asdict(m)
    out["series"] = [[d.isoformat(), v] for d, v in m.series]
    return out


async def snapshot_for(user_id: str, today: date | None = None) -> Snapshot:
    """这个人这一刻的数据：档案、每天的健康数据、全部指标（页面、问答、共享档案共用一份计算）。"""
    from mirobody.agent.tools.health_indicators_service import HealthIndicatorsService

    today = today or date.today()
    readings = await read_all(HealthIndicatorsService(), user_id, today)
    profile, _ = await profiles.load(user_id)
    adjust = await kcal_adjust(user_id)
    return Snapshot(profile, readings, tuple(compute_all(readings, profile, today, adjust)), today)


async def kcal_adjust(user_id: str) -> KcalAdjust | None:
    """现在的热量调整量（管家复盘里调的，§163 需求 6）；读不到时当作没有调整。"""
    from ironm_agent.diet_adjust import default_diet

    try:
        return await default_diet().current(user_id)
    except Exception as e:
        _log.warning("diet adjust unavailable: error_type=%s", type(e).__name__)
        return None


async def metrics_for(
    user_id: str, today: date | None = None
) -> tuple[list[Metric], dict[str, Any]]:
    """这个人的全部指标（页面和问答共用）。"""
    snap = await snapshot_for(user_id, today)
    readings, today = snap.readings, snap.today
    metrics = list(snap.metrics)
    dates = [
        d
        for s in (readings.weight, readings.resting_hr, readings.steps, readings.sleep_hours)
        for d, _ in s
    ]
    latest = max(dates) if dates else None
    meta = {
        "today": today.isoformat(),
        "as_of": latest.isoformat() if latest else None,
        "stale_days": (today - latest).days if latest else None,
        "unavailable": list(readings.errors),
    }
    return metrics, meta


@router.get("/iron/api/metrics")
async def get_metrics(user_id: str = Depends(_verify())) -> dict[str, Any]:
    try:
        metrics, meta = await metrics_for(user_id)
    except Exception as e:
        _log.error("metrics failed: error_type=%s", type(e).__name__)
        raise HTTPException(503, "指标暂时算不出来，请稍后再试") from e
    return {"metrics": [metric_json(m) for m in metrics], **meta}


@router.get("/iron/api/profile")
async def get_profile(user_id: str = Depends(_verify())) -> dict[str, Any]:
    p, sources = await profiles.load(user_id)
    return {
        "profile": {
            "height_cm": p.height_cm,
            "birth": p.birth.isoformat() if p.birth else None,
            "sex": p.sex,
            "goal": p.goal,
            "activity": p.activity,
        },
        "sources": sources,
        "options": {"goal": GOALS, "activity": {k: v[0] for k, v in ACTIVITY.items()}},
    }


@router.put("/iron/api/profile")
async def put_profile(
    body: profiles.ProfileIn, user_id: str = Depends(_verify())
) -> dict[str, Any]:
    old = (await profiles.load(user_id))[0].goal if "goal" in body.model_fields_set else None
    await profiles.save(user_id, body)
    if "goal" in body.model_fields_set and body.goal and body.goal != old:  # 目标类型真改了才叫醒管家（§151）
        coach_later(user_id, "改档案目标")
    return await get_profile(user_id)


@router.get("/iron/api/exercises")
async def get_exercises(user_id: str = Depends(_verify())) -> dict[str, Any]:
    lib = library()
    return {
        "parts": PARTS,
        "equipment": EQUIPMENT,
        "note": NOTE,
        "exercises": [
            {**x.model_dump(), "images": images_for(x.id), "gif": gif_for(x.id)}
            for x in lib.exercises
        ],
    }


# ---- 导入苹果健康 -------------------------------------------------------------------------

MAX_IMPORT_BYTES = 2 * 1024**3  # 健康 App 的导出包最多收 2GB
UPLOAD = File(..., description="健康 App 导出的 .zip（或其中的 export.xml）")
TZ = Form("", description="浏览器所在时区（IANA 名称），记录里没带时区时用")


def _zone(tz: str) -> str:
    try:
        ZoneInfo(tz)
    except Exception:
        return ""
    return tz


@router.post("/iron/api/import/apple")
async def import_apple(
    file: UploadFile = UPLOAD, tz: str = TZ, user_id: str = Depends(_verify())
) -> dict[str, Any]:
    if imports.running(user_id):
        raise HTTPException(409, "上一次导入还在进行，完成后再导入")
    suffix = Path((file.filename or "").lower()).suffix
    if suffix not in (".zip", ".xml"):
        raise HTTPException(400, "请上传健康 App 导出的 .zip 压缩包")
    fd, raw = tempfile.mkstemp(prefix="ironm-upload-", suffix=suffix)
    path, size = Path(raw), 0
    with os.fdopen(fd, "wb") as out:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_IMPORT_BYTES:
                break
            out.write(chunk)
    if size > MAX_IMPORT_BYTES or size == 0:
        path.unlink(missing_ok=True)
        raise HTTPException(413 if size else 400, "文件太大（超过 2GB）" if size else "文件是空的")
    job = imports.start(user_id, path, _zone(tz) or "UTC")
    return {"job": job.json()}


@router.get("/iron/api/import/apple")
async def import_apple_status(user_id: str = Depends(_verify())) -> dict[str, Any]:
    job = imports.latest(user_id)
    return {"job": job.json() if job else None}


# ---- 记忆接口：前端不显示（项目负责人决定），保留查看、修改、删除、暂停，留给以后的隐私设置或 App ----


def memory_store() -> MemoryStore:
    return default_store()


STORE = Depends(memory_store)  # 测试时用 dependency_overrides 换成内存版


def item_json(x: Item) -> dict[str, Any]:
    return {
        "id": x.id,
        "category": x.category,
        "content": x.content,
        "evidence": x.evidence,
        "origin": x.origin,
        "origin_label": ORIGINS[x.origin],
        "status": x.status,
        "expired": expired(x),
        "until": x.until.isoformat() if x.until else None,
        "created": x.created.isoformat(),
        "updated": x.updated.isoformat(),
    }


class MemoryEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=MAX_CONTENT)


class MemorySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paused: bool


@router.get("/iron/api/memory")
async def get_memory(
    user_id: str = Depends(_verify()), store: MemoryStore = STORE
) -> dict[str, Any]:
    items = await store.items(user_id)
    return {
        "paused": await store.paused(user_id),
        "categories": CATEGORIES,
        "items": [item_json(x) for x in items],
    }


@router.put("/iron/api/memory/{item_id}")
async def edit_memory(
    item_id: str,
    body: MemoryEdit,
    user_id: str = Depends(_verify()),
    store: MemoryStore = STORE,
) -> dict[str, Any]:
    content = body.content.strip()
    if not content:
        raise HTTPException(422, "内容不能为空")
    item = await store.edit(user_id, item_id, content)
    if item is None:
        raise HTTPException(404, "这条记忆不存在")
    return item_json(item)


@router.post("/iron/api/memory/{item_id}/confirm")
async def confirm_memory(
    item_id: str, user_id: str = Depends(_verify()), store: MemoryStore = STORE
) -> dict[str, Any]:
    item = await store.confirm(user_id, item_id)
    if item is None:
        raise HTTPException(404, "这条记忆不存在或不需要确认")
    return item_json(item)


@router.delete("/iron/api/memory/{item_id}")
async def delete_memory(
    item_id: str, user_id: str = Depends(_verify()), store: MemoryStore = STORE
) -> dict[str, Any]:
    if not await store.delete(user_id, item_id):
        raise HTTPException(404, "这条记忆不存在")
    return {"deleted": item_id}


@router.put("/iron/api/memory-settings")
async def memory_settings(
    body: MemorySettings,
    user_id: str = Depends(_verify()),
    store: MemoryStore = STORE,
) -> dict[str, Any]:
    await store.set_paused(user_id, body.paused)
    return {"paused": body.paused}


# ---- 训练计划、训练记录与预览（spec [2026-10-23] §9）；今日简报与每周复盘（§10）----------------------


def training_store() -> TrainingStore:
    return default_training()


TRAINING = Depends(training_store)  # 测试时用 dependency_overrides 换成内存版


@router.get("/iron/api/drafts/{draft_id}")
async def get_draft(
    draft_id: str, user_id: str = Depends(_verify()), store: TrainingStore = TRAINING
) -> dict[str, Any]:
    d = await store.draft(user_id, draft_id)
    if d is None:
        raise HTTPException(404, "这份预览不存在")
    return {"draft": d.json()}


async def _draft_action(
    store: TrainingStore, user_id: str, draft_id: str, action: str
) -> dict[str, Any]:
    d = await store.draft(user_id, draft_id)
    if d is None:
        raise HTTPException(404, "这份预览不存在")
    if action == "confirm":
        if d.state == "pending" and d.expired():
            raise HTTPException(410, "预览已经过期（超过 24 小时），请让教练重新生成")
        done = await store.confirm(user_id, draft_id)
    elif action == "cancel":
        done = await store.cancel(user_id, draft_id)
    else:
        done = await store.undo(user_id, draft_id)
    if done is None:
        now = await store.draft(user_id, draft_id)
        if now is not None and (
            (action == "confirm" and now.state == "confirmed")
            or (action == "cancel" and now.state == "cancelled")
            or (action == "undo" and now.state == "undone")
        ):
            return {"draft": now.json()}  # 已经做过了（比如点了两次）：不重复写入
        why = {
            "confirm": "这份预览已经处理过，不能再确认",
            "cancel": "这份预览已经处理过",
            "undo": "之后又改过计划，不能撤销这一次" if d.kind == "plan" else "这条记录不能撤销",
        }[action]
        raise HTTPException(409, why)
    _log.info("draft %s: kind=%s", action, done.kind)
    return {"draft": done.json()}


_BACKGROUND: set[asyncio.Task[Any]] = set()


def refresh_later(user_id: str, memory: MemoryStore, training: TrainingStore) -> None:
    """在后台更新训练记录得出的偏好；出错只记错误类型，不影响这次请求。"""

    async def go() -> None:
        try:
            await refresh_prefs(user_id, memory, training)
        except Exception as e:
            _log.warning("prefs refresh failed: error_type=%s", type(e).__name__)

    task = asyncio.create_task(go())
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)


def _targets_later(user_id: str, log: WorkoutLog) -> None:
    from ironm_agent import web_more

    web_more.targets_later(user_id, log)


@router.post("/iron/api/drafts/{draft_id}/confirm")
async def confirm_draft(
    draft_id: str,
    user_id: str = Depends(_verify()),
    store: TrainingStore = TRAINING,
    memory: MemoryStore = STORE,
    illness: Any = ILLNESS,
    goals: Any = GOAL,
    kitchen: Any = KITCHEN,
) -> dict[str, Any]:
    was = await store.draft(user_id, draft_id)
    if was is not None and was.kind == "diet" and not (was.state == "pending" and was.expired()):
        return await _confirm_diet(user_id, draft_id, store, kitchen)
    if was is not None and was.kind == "goal" and not (was.state == "pending" and was.expired()):
        # 改目标：确认了才写档案和目标表（§151）。这一次真把它从待确认改成已确认的才写，
        # 点两次、两个请求同时到都只写一次；写失败时已写的恢复、卡片作废，不留半截（复核 11-03）
        from ironm_agent import web_more

        done = await store.confirm(user_id, draft_id)
        if done is None:
            return await _draft_action(store, user_id, draft_id, "confirm")
        try:
            await web_more.apply_goal(user_id, done.json(), goals, store, memory)
        except Exception as e:
            _log.warning("goal apply failed: error_type=%s", type(e).__name__)
            await store.undo(user_id, draft_id)
            raise HTTPException(503, "这次没改成，目标还是原来的；请让教练重新出一张卡片") from e
        fresh = await store.draft(user_id, draft_id)
        return {"draft": (fresh or done).json()}
    out = await _draft_action(store, user_id, draft_id, "confirm")
    if out.get("draft", {}).get("kind") == "log":  # 记下了一次训练：后台更新训练记录得出的偏好
        refresh_later(user_id, memory, store)
        log = out["draft"].get("log") or {}
        try:  # 对话里记的训练确认后也叫醒管家定下次（§132）
            _targets_later(user_id, WorkoutLog.model_validate(log))
        except ValueError:
            _log.warning("next targets skipped: error_type=ValueError")
    plan_change_later(user_id, out.get("draft") or {})  # 按操作改的计划：记进调整经历（§45）
    coach_later(user_id, "确认方案")  # 计划或记录变了：管家重新评估（spec [2026-10-23] §23）
    return out


async def _confirm_diet(user_id: str, draft_id: str, store: TrainingStore, kitchen: Any) -> dict[str, Any]:
    """换饮食方案的卡片（§190）：真把它从待确认改成已确认的这一次才换，按确认时的热量目标算份数；
    换不成时卡片退回、计划不动。"""
    from ironm_agent.diet_library import by_id
    from ironm_agent.recipes import SlotRef
    from ironm_agent.web_diet_library import _target, apply_plan, apply_raw

    done = await store.confirm(user_id, draft_id)
    if done is None:
        return await _draft_action(store, user_id, draft_id, "confirm")
    try:
        diet = done.content.get("diet") or {}
        if diet.get("custom"):  # 按他情况排的（§192）：份数出卡片时已经按目标定好，原样换上
            raw = {s: {k: SlotRef.model_validate(v).model_dump(mode="json") for k, v in (diet["custom"].get(s) or {}).items()}
                   for s in ("weekday", "weekend")}  # fmt: skip
            await apply_raw(user_id, raw, kitchen, applied="custom", name=str(diet.get("name") or ""), draft=draft_id)
        else:
            p = by_id(str(diet.get("id") or ""))
            if p is None:
                raise LookupError("diet plan gone")
            target = await _target(user_id)
            await apply_plan(user_id, p, kitchen, target.kcal if target else None, draft=draft_id)
    except Exception as e:
        _log.warning("diet apply failed: error_type=%s", type(e).__name__)
        await store.undo(user_id, draft_id)
        raise HTTPException(503, "这次没换成，饮食计划还是原来的；请让 IronM 重新出一张卡片") from e
    fresh = await store.draft(user_id, draft_id)
    return {"draft": (fresh or done).json()}


@router.post("/iron/api/drafts/{draft_id}/cancel")
async def cancel_draft(
    draft_id: str, user_id: str = Depends(_verify()), store: TrainingStore = TRAINING
) -> dict[str, Any]:
    out = await _draft_action(store, user_id, draft_id, "cancel")
    from ironm_agent import web_more

    await web_more.coach_declined(user_id, out.get("draft") or {})  # 管家提的预览他不要：14 天内不再提（§182）
    return out


@router.post("/iron/api/drafts/{draft_id}/undo")
async def undo_draft(
    draft_id: str,
    user_id: str = Depends(_verify()),
    store: TrainingStore = TRAINING,
    memory: MemoryStore = STORE,
    goals: Any = GOAL,
    kitchen: Any = KITCHEN,
) -> dict[str, Any]:
    d = await store.draft(user_id, draft_id)
    if d is not None and d.kind == "diet" and d.state == "confirmed":  # 换饮食方案：放回换之前的计划（§190）
        from ironm_agent.web_diet_library import restore_plan

        if not await restore_plan(user_id, kitchen, draft=draft_id):
            raise HTTPException(409, "之后又换过饮食计划，不能撤销这一次")
        return await _draft_action(store, user_id, draft_id, "undo")
    if d is not None and d.kind == "goal" and d.state == "confirmed":  # §151
        from ironm_agent import web_more

        if not await web_more.goal_unchanged(user_id, d.json(), goals):
            raise HTTPException(409, "之后又改过目标，不能撤销这一次")
        out = await _draft_action(store, user_id, draft_id, "undo")
        fresh = await store.draft(user_id, draft_id)  # 确认时记下的"确认前"
        await web_more.restore_goal(user_id, fresh.json() if fresh is not None else out["draft"], goals, memory)
        return out
    out = await _draft_action(store, user_id, draft_id, "undo")
    plan_change_later(user_id, out.get("draft") or {}, undone=True)
    coach_later(user_id, "撤销方案")
    return out


class WorkoutIn(BaseModel):
    """首页一键记下今天的训练：按计划的哪一次、是否练完、感受、备注。"""

    model_config = ConfigDict(extra="forbid")

    session: str = Field(default="", max_length=16)
    items: list[LogItem] = Field(default_factory=list, max_length=15)  # 按今天的版本练时带上
    done: bool = True
    rpe: int | None = Field(default=None, ge=1, le=10)
    minutes: int | None = Field(default=None, ge=1, le=300)
    note: str = Field(default="", max_length=80)
    energy: Feeling | None = None  # 打卡多记的状态（§105）
    slept: Feeling | None = None
    sore: list[str] = Field(default_factory=list, max_length=len(SORE_PARTS))
    rest: RestWhy | None = None  # 今天没练：休息、生病、出差、太忙（不算练了）


@router.post("/iron/api/workouts")
async def add_workout(
    body: WorkoutIn,
    user_id: str = Depends(_verify()),
    store: TrainingStore = TRAINING,
    memory: MemoryStore = STORE,
    pain: Any = PAIN,
    illness: Any = ILLNESS,
    feel: Any = FEEL,
) -> dict[str, Any]:
    data = body.model_dump()
    if body.rest is not None:  # 没练的那条：不算练了（§105）
        data.update(done=False, items=[])
    try:
        log = WorkoutLog(day=date.today(), **data)
    except ValueError as err:
        raise HTTPException(422, "打卡的内容不对") from err
    row = await store.log(user_id, log)
    await after_workout(user_id, row.log, store, memory, pain, illness)
    await record_sore(feel, user_id, row.log)
    return {"workout": {"id": row.id, **row.log.model_dump(mode="json"), "line": row.log.line()}}


async def record_sore(feel: Any, user_id: str, log: WorkoutLog) -> None:
    """打卡说酸的部位记进肌肉酸痛（人体图上点"酸"的那份，§105）；记不下不影响打卡。"""
    from ironm_agent.muscle_feel import SORE_MUSCLES

    try:
        for part in log.sore:
            for code in SORE_MUSCLES.get(part, ()):
                await feel.add(user_id, code, "sore", log.day)
    except Exception as e:
        _log.warning("checkin sore record failed: error_type=%s", type(e).__name__)


async def after_workout(
    user_id: str,
    log: WorkoutLog,
    store: TrainingStore,
    memory: MemoryStore,
    pain: Any,
    illness: Any,
) -> None:
    """记下一次训练之后（打卡、训练记录器结束，§71）：备注由管家读、偏好、管家重新评估、定下次。
    不再按关键词从备注里记疼，也不再"练了一次就算病好了"（§163 规则不要）。"""
    from ironm_agent.web_more import body_later

    body_later(user_id, log.note, log.day, "打卡备注")  # 说了疼、病、累由管家读出来再记
    refresh_later(user_id, memory, store)  # 后台更新训练记录得出的偏好（spec [2026-10-23] §17）
    coach_later(user_id, "打卡")  # 管家重新评估当前方案（spec [2026-10-23] §23）
    _targets_later(user_id, log)  # 叫醒管家定下次怎么练（§132）


@router.delete("/iron/api/workouts/{workout_id}")
async def delete_workout(
    workout_id: str,
    user_id: str = Depends(_verify()),
    store: TrainingStore = TRAINING,
    photos: Any = PHOTOS,
) -> dict[str, Any]:
    if not await store.delete_workout(user_id, workout_id):
        raise HTTPException(404, "这条记录不存在")
    try:  # 打卡照片跟着记录一起删（§117）
        await photos.drop(user_id, workout_id)
    except Exception as e:
        _log.warning("checkin photo delete failed: error_type=%s", type(e).__name__)
    return {"deleted": workout_id}


async def _decided(user_id: str) -> dict[str, Any]:
    from ironm_agent import web_more

    return await web_more.decided_targets(user_id)


@router.get("/iron/api/training")
async def get_training(
    user_id: str = Depends(_verify()), store: TrainingStore = TRAINING, photos: Any = PHOTOS
) -> dict[str, Any]:
    today = date.today()
    plan = await store.plan(user_id)
    logs = await store.workouts(user_id, today - timedelta(days=42))
    found = targets(plan.plan if plan else None, [x.log for x in logs], await _decided(user_id))
    shown = [x for x in reversed(logs) if (today - x.log.day).days <= 30]
    try:  # 哪些打卡带了照片（§117）；读不到当作都没有
        with_photo = await photos.having(user_id, [x.id for x in shown])
    except Exception as e:
        _log.warning("checkin photos unavailable: error_type=%s", type(e).__name__)
        with_photo = set()
    return {
        "plan": plan.plan.model_dump(mode="json") if plan else None,
        "plan_lines": plan.plan.lines() if plan else [],
        "targets": {  # 每个动作的下次目标（spec [2026-10-23] §18 需求 4）
            k: {
                "text": t.text(),
                "why": t.why,
                "action": t.action,
                "weight_kg": t.weight_kg,
                "reps": t.reps,
                "sets": t.sets,
                "by": t.by,  # coach：管家练完后定的（§132）；last：管家没定，照上次（§163 需求 6）
            }
            for k, t in found.items()
        },
        "workouts": [
            {
                "id": x.id,
                **x.log.model_dump(mode="json"),
                "line": x.log.line(),
                "photo": x.id in with_photo,
            }
            for x in shown
        ],
    }


RISK_TITLES = {
    "bp_crisis": "血压很高：先别运动，尽快就医",
    "bp_high": "血压偏高：加大训练前先找医生",
    "rhr_high": "静息心率偏高：加大训练前先看医生",
    "pregnancy": "孕期：训练有要避开的动作",
    "cardiac": "心脏方面：加大强度前先问医生",
    "diabetes": "糖尿病：留意运动前后的血糖",
    "hypertension": "高血压：不憋气、不做大重量",
    "surgery": "近期手术：恢复训练前先问医生",
}


@router.get("/iron/api/brief")
async def get_brief(
    user_id: str = Depends(_verify()),
    store: TrainingStore = TRAINING,
    memory: MemoryStore = STORE,
    illness: Any = ILLNESS,
) -> dict[str, Any]:
    """首页的今日简报与每周复盘：只用规则，不调用模型。"""
    try:
        snap = await snapshot_for(user_id)
    except Exception as e:
        _log.error("brief failed: error_type=%s", type(e).__name__)
        raise HTTPException(503, "今天的简报暂时生成不了，请稍后再试") from e
    plan, logs, items = None, [], []
    try:  # 计划、记录、记忆读不到时，简报照样出（只是少了这部分）
        plan = await store.plan(user_id)
        logs = [x.log for x in await store.workouts(user_id, snap.today - timedelta(days=14))]
    except Exception as e:
        _log.warning("brief training unavailable: error_type=%s", type(e).__name__)
    try:
        items = [x for x in await memory.items(user_id) if x.status == "active"]
    except Exception as e:
        _log.warning("brief memory unavailable: error_type=%s", type(e).__name__)
    current = plan.plan if plan else None
    eps = await recent_illness(illness, user_id, snap.today)
    today = today_brief(snap, items, current, logs)
    # 只给这周的事实；规则的每周建议不给了，要不要调由管家复盘提（§163、§182）
    week = weekly_review(snap, current, logs, plan.since if plan else None, sick=sick_days(eps, snap.today))
    hero = hero_line(today, week)
    rainy = hot = False
    try:  # 鼓励的话会看今天的天气（spec [2026-10-23] §34）；取不到就不看
        wx = await weather.for_user(user_id)
        if wx is not None:
            level = weather.assess(wx).level
            rainy = level in ("indoor", "avoid") and wx.code >= 51
            hot = wx.temperature >= 35
    except Exception as e:
        _log.warning("brief weather unavailable: error_type=%s", type(e).__name__)
    hero["cheer"] = cheer(today, week, rainy=rainy, hot=hot, on=snap.today)
    # 安全提醒放首页（spec [2026-10-23] §42）：数据或记忆里的风险还在生效时，战报最上面一行，点开看原文
    alerts = [
        {"key": x.key, "title": RISK_TITLES.get(x.key, "健康提醒"), "text": x.note}
        for x in risks(snap.readings, items, snap.today)
    ]
    # 生病追问（§46）：从第二天起每天问一次，回答过就不再显示
    checkin = next(
        ({"id": e.id, "text": question(e, snap.today), "doctor": doctor(e, snap.today)}
         for e in illness_active(eps, snap.today) if due(e, snap.today)),
        None,
    )  # fmt: skip
    return {"today": today, "week": week, "hero": hero, "alerts": alerts, "checkin": checkin}


@router.get("/iron")
@router.get("/iron/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})


# 文件名里带版本号的（musclemap-v1.json）内容不会变：浏览器缓存一周，不再重新下载
_VERSIONED = re.compile(r"-v\d+\.")


@router.get("/iron/{name}")
async def asset(name: str) -> FileResponse:
    path = (WEB_DIR / name).resolve()
    if path.parent != WEB_DIR.resolve() or not path.is_file():
        raise HTTPException(404)
    cache = "public, max-age=604800, immutable" if _VERSIONED.search(name) else "no-cache"
    return FileResponse(path, headers={"Cache-Control": cache})


# 前端改版的接口（spec [2026-10-23] §13）放在 web_more.py，挂在同一个 router 上
from ironm_agent.web_more import router as _more  # noqa: E402

router.include_router(_more)

# 夯榜（spec [2026-10-23] §60）
from ironm_agent.web_tier import router as _tier  # noqa: E402

router.include_router(_tier)

# 夯榜改成排行榜（spec [2026-10-23] §72）
from ironm_agent.web_rank import router as _rank  # noqa: E402

router.include_router(_rank)

# 训练记录器（spec [2026-10-23] §71）
from ironm_agent.web_live import router as _live  # noqa: E402

router.include_router(_live)

# 计划页直接改（spec [2026-10-23] §106）
from ironm_agent.web_plan import router as _plan  # noqa: E402

router.include_router(_plan)

# 打卡照片（spec [2026-10-23] §117）
from ironm_agent.web_photo import router as _photo  # noqa: E402

router.include_router(_photo)

# 饮食：食物库、改份量、常吃的、食谱、饮食计划（spec [2026-10-23] §118）
from ironm_agent.web_diet import router as _diet  # noqa: E402

router.include_router(_diet)

# 打卡分享卡和周报（spec [2026-11-03] §147）
from ironm_agent.web_share import router as _share  # noqa: E402

router.include_router(_share)

# 认器械（spec [2026-11-03] §149）
from ironm_agent.web_machines import router as _machines  # noqa: E402

router.include_router(_machines)

# 用自己的模型（spec [2026-11-03] §153）
from ironm_agent.web_user_models import router as _my_model  # noqa: E402

router.include_router(_my_model)

# 图鉴里的方案库（spec [2026-11-05] §161）
from ironm_agent.web_atlas import router as _atlas  # noqa: E402

router.include_router(_atlas)

# 饮食方案库：看、套用成饮食计划、撤销（spec [2026-11-06] §184）
from ironm_agent.web_diet_library import router as _diet_library  # noqa: E402

router.include_router(_diet_library)

# 找回密码（spec [2026-11-03] §155）：从 mirobody 挪进 iron-m，mirobody 的代码一行不改（§168）
from ironm_agent.web_password import router as _password  # noqa: E402

router.include_router(_password)

# 账号与隐私（spec [2026-10-23] §180）：导出我的数据、注销账号
from ironm_agent.web_account import router as _account  # noqa: E402

router.include_router(_account)
