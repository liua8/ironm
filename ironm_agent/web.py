"""iron-m 的页面与接口，挂在 mirobody 同一个服务上（/iron/），登录沿用 mirobody 的令牌。"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from ironm_agent import imports
from ironm_agent import profile as profiles
from ironm_agent.brief import today_brief, weekly_review
from ironm_agent.casefile import Snapshot
from ironm_agent.exercises import EQUIPMENT, NOTE, PARTS, library
from ironm_agent.healthdata import read_all
from ironm_agent.memory_extract import MAX_CONTENT
from ironm_agent.memory_prefs import refresh as refresh_prefs
from ironm_agent.memory_store import CATEGORIES, ORIGINS, Item, MemoryStore, default_store
from ironm_agent.memory_view import expired
from ironm_agent.metrics import ACTIVITY, GOALS, Metric, compute_all
from ironm_agent.training import TrainingStore, WorkoutLog, default_training

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
    return Snapshot(profile, readings, tuple(compute_all(readings, profile, today)), today)


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
    await profiles.save(user_id, body)
    return await get_profile(user_id)


@router.get("/iron/api/exercises")
async def get_exercises(user_id: str = Depends(_verify())) -> dict[str, Any]:
    lib = library()
    return {
        "parts": PARTS,
        "equipment": EQUIPMENT,
        "note": NOTE,
        "exercises": [x.model_dump() for x in lib.exercises],
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


@router.post("/iron/api/drafts/{draft_id}/confirm")
async def confirm_draft(
    draft_id: str,
    user_id: str = Depends(_verify()),
    store: TrainingStore = TRAINING,
    memory: MemoryStore = STORE,
) -> dict[str, Any]:
    out = await _draft_action(store, user_id, draft_id, "confirm")
    if out.get("draft", {}).get("kind") == "log":  # 记下了一次训练：后台更新训练记录得出的偏好
        refresh_later(user_id, memory, store)
    return out


@router.post("/iron/api/drafts/{draft_id}/cancel")
async def cancel_draft(
    draft_id: str, user_id: str = Depends(_verify()), store: TrainingStore = TRAINING
) -> dict[str, Any]:
    return await _draft_action(store, user_id, draft_id, "cancel")


@router.post("/iron/api/drafts/{draft_id}/undo")
async def undo_draft(
    draft_id: str, user_id: str = Depends(_verify()), store: TrainingStore = TRAINING
) -> dict[str, Any]:
    return await _draft_action(store, user_id, draft_id, "undo")


class WorkoutIn(BaseModel):
    """首页一键记下今天的训练：按计划的哪一次、是否练完、感受、备注。"""

    model_config = ConfigDict(extra="forbid")

    session: str = Field(default="", max_length=16)
    done: bool = True
    rpe: int | None = Field(default=None, ge=1, le=10)
    note: str = Field(default="", max_length=80)


@router.post("/iron/api/workouts")
async def add_workout(
    body: WorkoutIn,
    user_id: str = Depends(_verify()),
    store: TrainingStore = TRAINING,
    memory: MemoryStore = STORE,
) -> dict[str, Any]:
    row = await store.log(user_id, WorkoutLog(day=date.today(), **body.model_dump()))
    refresh_later(
        user_id, memory, store
    )  # 打卡后在后台更新训练记录得出的偏好（spec [2026-10-23] §17）
    return {"workout": {"id": row.id, **row.log.model_dump(mode="json"), "line": row.log.line()}}


@router.delete("/iron/api/workouts/{workout_id}")
async def delete_workout(
    workout_id: str, user_id: str = Depends(_verify()), store: TrainingStore = TRAINING
) -> dict[str, Any]:
    if not await store.delete_workout(user_id, workout_id):
        raise HTTPException(404, "这条记录不存在")
    return {"deleted": workout_id}


@router.get("/iron/api/training")
async def get_training(
    user_id: str = Depends(_verify()), store: TrainingStore = TRAINING
) -> dict[str, Any]:
    today = date.today()
    plan = await store.plan(user_id)
    logs = await store.workouts(user_id, today - timedelta(days=30))
    return {
        "plan": plan.plan.model_dump(mode="json") if plan else None,
        "plan_lines": plan.plan.lines() if plan else [],
        "workouts": [
            {"id": x.id, **x.log.model_dump(mode="json"), "line": x.log.line()}
            for x in reversed(logs)
        ],
    }


@router.get("/iron/api/brief")
async def get_brief(
    user_id: str = Depends(_verify()),
    store: TrainingStore = TRAINING,
    memory: MemoryStore = STORE,
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
    return {
        "today": today_brief(snap, items, current, logs),
        "week": weekly_review(snap, current, logs, plan.since if plan else None),
    }


@router.get("/iron")
@router.get("/iron/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@router.get("/iron/{name}")
async def asset(name: str) -> FileResponse:
    path = (WEB_DIR / name).resolve()
    if path.parent != WEB_DIR.resolve() or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


# 前端改版的接口（spec [2026-10-23] §13）放在 web_more.py，挂在同一个 router 上
from ironm_agent.web_more import router as _more  # noqa: E402

router.include_router(_more)
