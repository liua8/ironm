"""iron-m 的页面与接口，挂在 mirobody 同一个服务上（/iron/），登录沿用 mirobody 的令牌。"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from ironm_agent import profile as profiles
from ironm_agent.healthdata import read_all
from ironm_agent.memory_extract import MAX_CONTENT
from ironm_agent.memory_store import CATEGORIES, ORIGINS, Item, MemoryStore, default_store
from ironm_agent.memory_view import expired
from ironm_agent.metrics import ACTIVITY, GOALS, Metric, compute_all

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


async def metrics_for(
    user_id: str, today: date | None = None
) -> tuple[list[Metric], dict[str, Any]]:
    """这个人的全部指标（页面和问答共用）。"""
    from mirobody.agent.tools.health_indicators_service import HealthIndicatorsService

    today = today or date.today()
    readings = await read_all(HealthIndicatorsService(), user_id, today)
    profile, _ = await profiles.load(user_id)
    metrics = compute_all(readings, profile, today)
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


# ---- 我的记忆 ----------------------------------------------------------------------------


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
