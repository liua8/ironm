"""前端改版用到的接口（spec [2026-10-23] §13）：城市与天气、训练日历、肌肉人体图、动作视频、饮食记录与推荐。

挂在 web.router 上（同一个服务、同一套登录）；只读写 iron-m 自己的表和文件，不改 mirobody。
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from ironm_agent import weather
from ironm_agent.exercises import library
from ironm_agent.llm import TurnLLM, load_models
from ironm_agent.meals import (
    MAX_PHOTO_BYTES,
    MEAL_KINDS,
    Appetite,
    DayContext,
    Macros,
    MealKind,
    MealStore,
    default_meals,
    estimate,
    preset_meal,
    presets,
    recommend,
    totals,
)
from ironm_agent.memory_store import MemoryStore
from ironm_agent.metrics import GOALS
from ironm_agent.protools.muscle_map import muscle_map
from ironm_agent.training import TrainingStore

_log = logging.getLogger("ironm_agent.web_more")

ROOT = Path(__file__).resolve().parents[1]
VIDEO_TYPES = {"video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov"}
MAX_VIDEO_BYTES = 200 * 1024 * 1024
PHOTO_TYPES = ("image/jpeg", "image/png", "image/webp")


def _verify() -> Any:
    from mirobody.server.auth import verify_token

    return verify_token


def _web() -> Any:
    from ironm_agent import web

    return web


def training_store() -> TrainingStore:
    return _web().training_store()  # type: ignore[no-any-return]


def memory_store() -> MemoryStore:
    return _web().memory_store()  # type: ignore[no-any-return]


def meal_store() -> MealStore:
    return default_meals()


def video_dir() -> Path:
    """动作视频放在本机的数据目录（不进仓库）。"""
    return Path(os.environ.get("IRONM_DATA_DIR") or ROOT / "data") / "videos"


TRAINING = Depends(training_store)
MEMORY = Depends(memory_store)
MEALS = Depends(meal_store)  # 测试时用 dependency_overrides 换成内存版
UPLOAD = File(...)
PHOTO = File(None)

router = APIRouter()


# ---- 管理员（官方上传视频）------------------------------------------------------------------


async def _email(user_id: str) -> str:
    if not user_id.isdigit():
        return ""
    from mirobody.utils.db import execute_query

    rows = await execute_query(
        "SELECT email FROM health_app_user WHERE id = :id", {"id": int(user_id)}, log_sql=False
    )
    return str(rows[0].get("email") or "") if isinstance(rows, list) and rows else ""


async def is_admin(user_id: str) -> bool:
    """配置 IRONM_ADMINS（逗号分隔的账号编号或邮箱）里的人是管理员。"""
    names = {x.strip().lower() for x in os.environ.get("IRONM_ADMINS", "").split(",") if x.strip()}
    if not names:
        return False
    if user_id.lower() in names:
        return True
    try:
        return (await _email(user_id)).lower() in names
    except Exception as e:
        _log.warning("admin check failed: error_type=%s", type(e).__name__)
        return False


@router.get("/iron/api/me")
async def get_me(user_id: str = Depends(_verify())) -> dict[str, Any]:
    return {"admin": await is_admin(user_id)}


# ---- 城市与天气 ------------------------------------------------------------------------------


class PlaceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    city: str = Field(min_length=1, max_length=30)


@router.get("/iron/api/place")
async def get_place(user_id: str = Depends(_verify())) -> dict[str, Any]:
    city, place = await weather.load_place(user_id)
    return {"city": city, "label": place.name if place else ""}


@router.put("/iron/api/place")
async def put_place(body: PlaceIn, user_id: str = Depends(_verify())) -> dict[str, Any]:
    try:
        place = await weather.geocode(body.city)
    except Exception as e:
        _log.warning("geocode failed: error_type=%s", type(e).__name__)
        raise HTTPException(503, "暂时查不到城市，请稍后再试") from e
    if place is None:
        raise HTTPException(404, "没有找到这个城市，换个写法试试（比如“杭州”）")
    await weather.save_place(user_id, body.city, place)
    return {"city": body.city.strip(), "label": place.name}


def weather_json(w: weather.Weather | None, has_city: bool) -> dict[str, Any]:
    if not has_city:
        return {"status": "no_city"}
    if w is None:
        return {"status": "unavailable", "message": "暂时取不到天气"}
    advice = weather.assess(w)
    a = w.aqi
    return {
        "status": "ok",
        "place": w.place,
        "text": w.text,
        "temperature": round(w.temperature),
        "feels_like": round(w.feels_like),
        "humidity": w.humidity,
        "wind_kmh": w.wind_kmh,
        "aqi": a,
        "aqi_level": weather.aqi_level(a)[0] if a is not None else None,
        "observed": w.observed,
        "advice": {
            "level": advice.level,
            "name": advice.name,
            "reasons": list(advice.reasons),
            "sources": list(advice.sources),
        },
    }


@router.get("/iron/api/weather")
async def get_weather(user_id: str = Depends(_verify())) -> dict[str, Any]:
    try:
        _, place = await weather.load_place(user_id)
    except Exception as e:
        _log.warning("place unavailable: error_type=%s", type(e).__name__)
        return {"status": "unavailable", "message": "暂时取不到天气"}
    return weather_json(await weather.safe_fetch(place), place is not None)


# ---- 训练日历与肌肉人体图 -------------------------------------------------------------------

_MONTH = re.compile(r"^\d{4}-\d{2}$")


@router.get("/iron/api/calendar")
async def get_calendar(
    month: str = "", user_id: str = Depends(_verify()), store: TrainingStore = TRAINING
) -> dict[str, Any]:
    today = date.today()
    if month and not _MONTH.match(month):
        raise HTTPException(422, "月份写成 2026-10 这样")
    first = date.fromisoformat(f"{month}-01") if month else today.replace(day=1)
    nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    logs = await store.workouts(user_id, first)
    days: dict[str, list[dict[str, Any]]] = {}
    for x in sorted(logs, key=lambda r: r.log.day):
        if x.log.day >= nxt:
            continue
        days.setdefault(x.log.day.isoformat(), []).append(
            {
                "id": x.id,
                "done": x.log.done,
                "session": x.log.session,
                "rpe": x.log.rpe,
                "line": x.log.line(),
            }
        )
    return {
        "month": first.strftime("%Y-%m"),
        "today": today.isoformat(),
        "days": days,
        "done_days": sorted(d for d, v in days.items() if any(e["done"] for e in v)),
    }


@router.get("/iron/api/muscles")
async def get_muscles(
    user_id: str = Depends(_verify()), store: TrainingStore = TRAINING
) -> dict[str, Any]:
    today = date.today()
    plan = await store.plan(user_id)
    logs = [x.log for x in await store.workouts(user_id, today - timedelta(days=27))]
    return muscle_map(logs, today, plan.plan if plan else None)


# ---- 动作视频（官方上传）--------------------------------------------------------------------

_IDS: set[str] | None = None


def _exercise_ids() -> set[str]:
    global _IDS
    if _IDS is None:
        _IDS = {x.id for x in library().exercises}
    return _IDS


def _video_path(exercise_id: str) -> Path | None:
    for ext in VIDEO_TYPES.values():
        p = video_dir() / f"{exercise_id}{ext}"
        if p.exists():
            return p
    return None


@router.get("/iron/api/videos")
async def list_videos(user_id: str = Depends(_verify())) -> dict[str, Any]:
    return {"videos": sorted(i for i in _exercise_ids() if _video_path(i))}


@router.post("/iron/api/exercises/{exercise_id}/video")
async def upload_video(
    exercise_id: str, file: UploadFile = UPLOAD, user_id: str = Depends(_verify())
) -> dict[str, Any]:
    if not await is_admin(user_id):
        raise HTTPException(403, "只有管理员能上传动作视频")
    if exercise_id not in _exercise_ids():
        raise HTTPException(404, "动作库里没有这个动作")
    ext = VIDEO_TYPES.get(file.content_type or "")
    if ext is None:
        raise HTTPException(415, "只支持 MP4、WebM、MOV 视频")
    data = await file.read(MAX_VIDEO_BYTES + 1)
    if len(data) > MAX_VIDEO_BYTES:
        raise HTTPException(413, "视频不能超过 200MB")
    folder = video_dir()
    folder.mkdir(parents=True, exist_ok=True)
    old = _video_path(exercise_id)
    tmp = folder / f".{exercise_id}{ext}.part"
    tmp.write_bytes(data)
    if old is not None and old.suffix != ext:
        old.unlink()
    tmp.replace(folder / f"{exercise_id}{ext}")
    _log.info("video uploaded: exercise=%s bytes=%d", exercise_id, len(data))
    return {"exercise": exercise_id, "video": f"/iron/api/exercises/{exercise_id}/video"}


@router.delete("/iron/api/exercises/{exercise_id}/video")
async def delete_video(exercise_id: str, user_id: str = Depends(_verify())) -> dict[str, Any]:
    if not await is_admin(user_id):
        raise HTTPException(403, "只有管理员能删除动作视频")
    p = _video_path(exercise_id) if exercise_id in _exercise_ids() else None
    if p is None:
        raise HTTPException(404, "这个动作没有视频")
    p.unlink()
    return {"deleted": exercise_id}


@router.get("/iron/api/exercises/{exercise_id}/video")
async def get_video(exercise_id: str) -> FileResponse:
    """动作教学视频是公开内容（不含个人信息）；<video> 标签带不了登录凭证，所以不验证登录。"""
    p = _video_path(exercise_id) if exercise_id in _exercise_ids() else None
    if p is None:
        raise HTTPException(404, "这个动作还没有视频")
    return FileResponse(p, headers={"Cache-Control": "public, max-age=3600"})


# ---- 饮食记录与推荐 -------------------------------------------------------------------------


async def _targets(user_id: str) -> tuple[Macros | None, str, Any]:
    """今日目标（与数据页同一份计算）、目标名称、这一刻的数据。"""
    snap = await _web().snapshot_for(user_id)
    by = {m.key: m for m in snap.metrics}
    kcal, protein = by.get("kcal_target"), by.get("protein_target")
    target = None
    if kcal is not None and kcal.value and protein is not None and protein.value:
        target = Macros(kcal=kcal.value, protein_g=protein.value, carbs_g=0, fat_g=0)
    return target, GOALS.get(snap.profile.goal or "", ""), snap


def _day(day: str) -> date:
    if not day:
        return date.today()
    try:
        return date.fromisoformat(day)
    except ValueError as e:
        raise HTTPException(422, "日期写成 2026-10-23 这样") from e


def _kind(kind: str) -> MealKind:
    if kind not in MEAL_KINDS:
        raise HTTPException(422, "餐次只能是早餐、午餐、晚餐、加餐")
    return kind


async def _day_json(user_id: str, day: date, store: MealStore) -> dict[str, Any]:
    meals = await store.day(user_id, day)
    out: dict[str, Any] = {
        "day": day.isoformat(),
        "meals": [m.json() for m in meals],
        "totals": totals(meals).model_dump(),
    }
    try:
        target, goal, _ = await _targets(user_id)
    except Exception as e:  # 目标算不出来时，记录照样能看
        _log.warning("meal targets unavailable: error_type=%s", type(e).__name__)
        target, goal = None, ""
    out["target"] = target.model_dump() if target else None
    out["goal"] = goal
    return out


@router.get("/iron/api/meals")
async def get_meals(
    day: str = "", user_id: str = Depends(_verify()), store: MealStore = MEALS
) -> dict[str, Any]:
    return await _day_json(user_id, _day(day), store)


@router.post("/iron/api/meals")
async def add_meal(
    said: str = Form(""),
    kind: str = Form("午餐"),
    photo: UploadFile | None = PHOTO,
    user_id: str = Depends(_verify()),
    store: MealStore = MEALS,
) -> dict[str, Any]:
    """拍照加描述记一餐：营养估算热量和三大营养素（写明是估算）。"""
    meal_kind = _kind(kind)
    said = said.strip()[:120]
    data: bytes | None = None
    mime = ""
    if photo is not None and photo.filename:
        mime = photo.content_type or ""
        if mime not in PHOTO_TYPES:
            raise HTTPException(415, "照片只支持 JPG、PNG、WebP")
        data = await photo.read(MAX_PHOTO_BYTES + 1)
        if len(data) > MAX_PHOTO_BYTES:
            raise HTTPException(413, "照片不能超过 5MB")
    if not said and data is None:
        raise HTTPException(422, "拍张照片或写一句描述")
    import base64

    image = (
        {
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"},
        }
        if data
        else None
    )
    meal = await estimate(TurnLLM(load_models(), os.environ), said, meal_kind, image)
    if meal is None:
        raise HTTPException(503, "这次没能估算，请稍后再试，或者换一张更清楚的照片")
    row = await store.add(user_id, date.today(), meal, data, mime)
    _log.info("meal added: photo=%s", data is not None)
    return {"meal": row.json(), **(await _day_json(user_id, row.day, store))}


class PresetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset: str = Field(min_length=1, max_length=40)
    kind: str = "午餐"


@router.get("/iron/api/meals/presets")
async def get_presets(user_id: str = Depends(_verify())) -> dict[str, Any]:
    return {
        "presets": [p.model_dump() for p in presets()],
        "note": "按常见分量估算，实际随做法和分量变化（内容待审定）",
    }


@router.post("/iron/api/meals/preset")
async def add_preset(
    body: PresetIn, user_id: str = Depends(_verify()), store: MealStore = MEALS
) -> dict[str, Any]:
    found = next((p for p in presets() if p.id == body.preset), None)
    if found is None:
        raise HTTPException(404, "没有这个减脂餐")
    row = await store.add(user_id, date.today(), preset_meal(found, _kind(body.kind)))
    return {"meal": row.json(), **(await _day_json(user_id, row.day, store))}


@router.delete("/iron/api/meals/{meal_id}")
async def delete_meal(
    meal_id: str, user_id: str = Depends(_verify()), store: MealStore = MEALS
) -> dict[str, Any]:
    if not await store.delete(user_id, meal_id):
        raise HTTPException(404, "这条记录不存在")
    return {"deleted": meal_id}


@router.get("/iron/api/meals/{meal_id}/photo")
async def get_meal_photo(
    meal_id: str, user_id: str = Depends(_verify()), store: MealStore = MEALS
) -> Response:
    found = await store.photo(user_id, meal_id)
    if found is None:
        raise HTTPException(404, "没有这张照片")
    return Response(
        found[0], media_type=found[1], headers={"Cache-Control": "private, max-age=600"}
    )


class RecommendIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = "午餐"
    appetite: Appetite = "正常"


@router.post("/iron/api/meals/recommend")
async def recommend_meal(
    body: RecommendIn,
    user_id: str = Depends(_verify()),
    store: MealStore = MEALS,
    training: TrainingStore = TRAINING,
    memory: MemoryStore = MEMORY,
) -> dict[str, Any]:
    """营养按目标、今天还差多少、天气、身体状态、胃口、饮食限制推荐一餐。"""
    from ironm_agent.casefile import readiness

    today = date.today()
    try:
        target, goal, snap = await _targets(user_id)
    except Exception as e:
        _log.warning("recommend targets unavailable: error_type=%s", type(e).__name__)
        target, goal, snap = None, "", None
    eaten = totals(await store.day(user_id, today))
    limits: tuple[str, ...] = ()
    try:
        limits = tuple(
            x.content for x in await memory.items(user_id)
            if x.status == "active" and x.category in ("diet", "preference")
        )  # fmt: skip
    except Exception as e:
        _log.warning("recommend memory unavailable: error_type=%s", type(e).__name__)
    trained = False
    try:
        trained = any(
            x.log.done and x.log.day == today for x in await training.workouts(user_id, today)
        )
    except Exception as e:
        _log.warning("recommend training unavailable: error_type=%s", type(e).__name__)
    ctx = DayContext(
        kind=_kind(body.kind),
        appetite=body.appetite,
        goal=goal,
        target=target,
        eaten=eaten,
        weather=weather.case_line(await weather.for_user(user_id)),
        state=readiness(snap.readings, "", today).line() if snap is not None else "",
        limits=limits,
        trained_today=trained,
    )
    rec, problem = await recommend(TurnLLM(load_models(), os.environ), ctx)
    if rec is None:
        raise HTTPException(503, "这次没能生成推荐，请稍后再试")
    rest = ctx.remaining()
    return {
        "recommendation": rec.model_dump(),
        "total": rec.total().model_dump(),
        "remaining": rest.model_dump() if rest else None,
        "warning": problem,
        "considered": [x for x in (
            f"胃口：{body.appetite}", goal and f"目标：{goal}",
            ctx.weather and "天气", ctx.state and "今天的身体状态",
            limits and "饮食限制与喜好", trained and "今天已经练过",
        ) if x],
    }  # fmt: skip


class RecordIn(BaseModel):
    """把一份推荐直接记为这一餐（营养是推荐里估算的）。"""

    model_config = ConfigDict(extra="forbid")

    kind: str = "午餐"
    name: str = Field(min_length=1, max_length=40)
    items: list[str] = Field(default_factory=list, max_length=12)
    macros: Macros


@router.post("/iron/api/meals/record")
async def record_meal(
    body: RecordIn, user_id: str = Depends(_verify()), store: MealStore = MEALS
) -> dict[str, Any]:
    from ironm_agent.meals import Meal

    meal = Meal(
        kind=_kind(body.kind),
        name=body.name,
        items=[x[:40] for x in body.items],
        macros=body.macros.rounded(),
        note="按推荐记下，营养是估算的",
    )
    row = await store.add(user_id, date.today(), meal)
    return {"meal": row.json(), **(await _day_json(user_id, row.day, store))}


# ---- 每周复盘直接出调整方案（spec [2026-10-23] §18 需求 1）---------------------------------------


def make_agent(training: TrainingStore, memory: MemoryStore) -> Any:
    """生成调整方案用的 Agent：和对话里改计划走同一条链路（测试时换成假的）。"""
    from ironm_agent.plugin import IronMAgent

    agent = IronMAgent(training=training, memory=memory)
    agent._remember_on = False  # 这不是用户说的话，不提取记忆
    return agent


@router.post("/iron/api/review/proposal")
async def review_proposal(
    user_id: str = Depends(_verify()),
    training: TrainingStore = TRAINING,
    memory: MemoryStore = MEMORY,
) -> dict[str, Any]:
    from ironm_agent.brief import weekly_review
    from ironm_agent.plugin import REVIEW_ASK, REVIEW_MAX_DAYS
    from ironm_agent.protools.plan_check import changed_days
    from ironm_agent.training import parse_plan

    stored = await training.plan(user_id)
    if stored is None:
        raise HTTPException(409, "还没有训练计划：先让教练排一份")
    snap = await _web().snapshot_for(user_id)
    logs = [x.log for x in await training.workouts(user_id, snap.today - timedelta(days=14))]
    tips = weekly_review(snap, stored.plan, logs, stored.since)["tips"]
    if not tips:
        return {"status": "no_change", "message": "这周没有需要调整的地方，照计划来。"}
    ask = f"{REVIEW_ASK}（每次最多改两处，只改需要改的地方）：" + "".join(tips)
    agent = make_agent(training, memory)
    msgs = [{"role": "user", "content": ask}]
    blocks = [b async for b in agent.generate_response(user_id, msgs, session_id="")]
    card = next(
        (
            b
            for b in blocks
            if b.get("type") == "tool_call" and str(b.get("id", "")).startswith("card-")
        ),
        None,
    )
    answer = "".join(str(b.get("text", "")) for b in blocks if b.get("type") == "text")
    if card is None:
        return {
            "status": "failed",
            "message": "这次没能生成调整方案，可以到对话里让教练改。",
            "answer": answer,
        }
    draft = await training.draft(user_id, str(card["id"])[len("card-") :])
    if draft is None:
        raise HTTPException(500, "调整方案没有保存成功，请再试一次")
    new = parse_plan(draft.content.get("plan"))[0]
    n = changed_days(new, stored.plan) if new is not None else 0
    return {
        "status": "ok",
        "tips": tips,
        "answer": answer,
        "draft": draft.json(),
        "changed_days": n,
        "warning": f"这份方案改动了 {n} 天，超过了每次最多改 {REVIEW_MAX_DAYS} 天"
        if n > REVIEW_MAX_DAYS
        else "",
    }
