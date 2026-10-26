"""前端改版用到的接口（spec [2026-10-23] §13）：城市与天气、训练日历、肌肉人体图、动作视频、饮食记录与推荐。

挂在 web.router 上（同一个服务、同一套登录）；只读写 iron-m 自己的表和文件，不改 mirobody。
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

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
        "forecast": [_forecast_json(d) for d in w.days],
    }


def _forecast_json(d: weather.Day) -> dict[str, Any]:
    """一天的预报和对训练的影响（首页日历用，spec [2026-10-23] §33）。"""
    advice = weather.assess_day(d)
    return {"date": d.day, "text": d.text, "tmax": round(d.tmax), "tmin": round(d.tmin), "rain": d.rain,
            "level": advice.level, "name": advice.name, "reasons": list(advice.reasons)}  # fmt: skip


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


def feel_store() -> Any:
    from ironm_agent.muscle_feel import default_feel

    return default_feel()


FEEL = Depends(feel_store)  # 测试时用 dependency_overrides 换成内存版


@router.get("/iron/api/muscles")
async def get_muscles(
    user_id: str = Depends(_verify()), store: TrainingStore = TRAINING, feel: Any = FEEL
) -> dict[str, Any]:
    today = date.today()
    plan = await store.plan(user_id)
    # 恢复要看"4 周内练过没有"：多读一段
    logs = [x.log for x in await store.workouts(user_id, today - timedelta(days=35))]
    return muscle_map(logs, today, plan.plan if plan else None, await feel.latest(user_id))


class FeelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    muscle: str
    feel: Literal["sore", "fine"]


@router.post("/iron/api/muscles/feel")
async def post_muscle_feel(
    body: FeelIn,
    user_id: str = Depends(_verify()),
    store: TrainingStore = TRAINING,
    feel: Any = FEEL,
) -> dict[str, Any]:
    """本人说某块肌肉还酸 / 已经不酸了（spec [2026-10-23] §30）：恢复判断以本人说的为准。"""
    from ironm_agent.protools.muscle_map import MUSCLES

    if body.muscle not in MUSCLES:
        raise HTTPException(422, "没有这块肌肉")
    await feel.add(user_id, body.muscle, body.feel, date.today())
    return await get_muscles(user_id, store, feel)


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


@router.get("/iron/api/exercise-images/{name}")
async def get_exercise_image(name: str) -> FileResponse:
    """动作配图（spec [2026-10-23] §32）：公开内容（来自 wger，CC BY-SA），<img> 带不了登录凭证，不验证登录。"""
    from ironm_agent.exercise_images import image_path

    p = image_path(name)
    if p is None:
        raise HTTPException(404, "没有这张图")
    return FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})


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
    coach_later(user_id, "记饮食")
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
    coach_later(user_id, "记饮食")
    return {"meal": row.json(), **(await _day_json(user_id, row.day, store))}


@router.delete("/iron/api/meals/{meal_id}")
async def delete_meal(
    meal_id: str, user_id: str = Depends(_verify()), store: MealStore = MEALS
) -> dict[str, Any]:
    if not await store.delete(user_id, meal_id):
        raise HTTPException(404, "这条记录不存在")
    coach_later(user_id, "记饮食")
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
    coach_later(user_id, "记饮食")
    return {"meal": row.json(), **(await _day_json(user_id, row.day, store))}


# ---- 每周复盘直接出调整方案（spec [2026-10-23] §18 需求 1）---------------------------------------


def make_agent(training: TrainingStore, memory: MemoryStore) -> Any:
    """生成调整方案用的 Agent：和对话里改计划走同一条链路（测试时换成假的）。"""
    from ironm_agent.plugin import IronMAgent

    agent = IronMAgent(training=training, memory=memory)
    agent._remember_on = False  # 这不是用户说的话，不提取记忆
    return agent


# ---- 触发型调整（spec [2026-10-23] §18 需求 5）---------------------------------------------------

TRIGGER_ASK = "按首页的提醒调整训练计划"


def pain_store() -> Any:
    from ironm_agent.triggers import default_pain

    return default_pain()


PAIN = Depends(pain_store)  # 测试时用 dependency_overrides 换成内存版


async def _triggers(user_id: str, training: TrainingStore, pain: Any, today: date) -> list[Any]:
    from ironm_agent.triggers import PAIN_DAYS, PLATEAU_LOOKBACK, detect

    stored = await training.plan(user_id)
    logs = [
        x.log for x in await training.workouts(user_id, today - timedelta(days=PLATEAU_LOOKBACK))
    ]
    pains = await pain.since(user_id, today - timedelta(days=PAIN_DAYS))
    return detect(
        stored.plan if stored else None, logs, stored.since if stored else None, pains, today
    )


@router.get("/iron/api/triggers")
async def get_triggers(
    user_id: str = Depends(_verify()), training: TrainingStore = TRAINING, pain: Any = PAIN
) -> dict[str, Any]:
    found = await _triggers(user_id, training, pain, date.today())
    return {"triggers": [
        {"kind": t.kind, "title": t.title, "detail": t.detail, "action": t.action} for t in found
    ]}  # fmt: skip


@router.post("/iron/api/review/proposal")
async def review_proposal(
    trigger: str = "",
    user_id: str = Depends(_verify()),
    training: TrainingStore = TRAINING,
    memory: MemoryStore = MEMORY,
    pain: Any = PAIN,
) -> dict[str, Any]:
    """按每周复盘（或首页的某条提醒，trigger 为提醒的种类）生成调整方案；提醒在服务端重新判断。"""
    from ironm_agent.brief import weekly_review
    from ironm_agent.plugin import REVIEW_ASK, REVIEW_MAX_DAYS
    from ironm_agent.protools.plan_check import changed_days
    from ironm_agent.training import parse_plan

    stored = await training.plan(user_id)
    if stored is None:
        raise HTTPException(409, "还没有训练计划：先让教练排一份")
    snap = await _web().snapshot_for(user_id)
    if trigger:
        found = await _triggers(user_id, training, pain, snap.today)
        hit = next((t for t in found if t.kind == trigger and t.action == "proposal"), None)
        if hit is None:
            return {"status": "no_change", "message": "这条提醒已经不需要处理了。"}
        tips = [hit.tip]
        ask = f"{TRIGGER_ASK}（只改需要改的地方）：{hit.tip}"
    else:
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
        if n > REVIEW_MAX_DAYS and not trigger
        else "",
    }


# ---- 两周饮食复盘（spec [2026-10-23] §18 需求 2）------------------------------------------------


def diet_store() -> Any:
    from ironm_agent.diet_adjust import default_diet

    return default_diet()


DIET = Depends(diet_store)  # 测试时用 dependency_overrides 换成内存版


async def _diet_state(user_id: str, diet: Any) -> dict[str, Any]:
    from ironm_agent.diet_adjust import propose

    snap = await _web().snapshot_for(user_id)
    current = await diet.current(user_id)
    proposal, why = propose(snap.metrics, snap.profile, current, snap.today)
    target = next((m for m in snap.metrics if m.key == "kcal_target"), None)
    return {
        "target": target.value if target else None,
        "current": (
            {"kcal": current.kcal, "since": current.since.isoformat(), "reason": current.reason}
            if current
            else None
        ),
        "proposal": (
            {
                "delta": proposal.delta,
                "total": proposal.total,
                "before": proposal.before,
                "after": proposal.after,
                "reason": proposal.reason,
                "basis": proposal.basis,
            }
            if proposal
            else None
        ),
        "message": why,
    }


@router.get("/iron/api/diet/review")
async def diet_review(user_id: str = Depends(_verify()), diet: Any = DIET) -> dict[str, Any]:
    return await _diet_state(user_id, diet)


@router.post("/iron/api/diet/adjust")
async def diet_apply(user_id: str = Depends(_verify()), diet: Any = DIET) -> dict[str, Any]:
    """确认调整：服务端按当前数据重新算一遍方案再保存（不信任页面传来的数字）。"""
    from ironm_agent.diet_adjust import propose
    from ironm_agent.metrics import KcalAdjust

    snap = await _web().snapshot_for(user_id)
    proposal, why = propose(snap.metrics, snap.profile, await diet.current(user_id), snap.today)
    if proposal is None:
        raise HTTPException(409, why or "这次不需要调整")
    await diet.apply(user_id, KcalAdjust(proposal.total, snap.today, proposal.reason))
    _log.info("diet adjusted: delta=%d", proposal.delta)
    coach_later(user_id, "确认方案")
    return await _diet_state(user_id, diet)


@router.post("/iron/api/diet/adjust/undo")
async def diet_undo(user_id: str = Depends(_verify()), diet: Any = DIET) -> dict[str, Any]:
    if await diet.current(user_id) is None:
        raise HTTPException(404, "现在没有热量调整")
    await diet.undo(user_id)
    coach_later(user_id, "撤销方案")
    return await _diet_state(user_id, diet)


# ---- 今天的版本（spec [2026-10-23] §18 需求 3）---------------------------------------------------


@router.get("/iron/api/today")
async def get_today(
    minutes: int | None = None,
    tired: bool = False,
    user_id: str = Depends(_verify()),
    training: TrainingStore = TRAINING,
) -> dict[str, Any]:
    """按今天的状态、天气和可用时间，用规则改出今天的版本；原计划不变。"""
    from ironm_agent.casefile import readiness
    from ironm_agent.today import build
    from ironm_agent.triggers import gap_scale

    if minutes is not None and not 10 <= minutes <= 180:
        raise HTTPException(422, "可用时间要在 10 到 180 分钟之间")
    stored = await training.plan(user_id)
    today = date.today()
    if stored is None:
        return {"status": "no_plan"}
    session = stored.plan.session_on(today)
    if session is None:
        return {"status": "rest"}
    snap = await _web().snapshot_for(user_id)
    state = readiness(snap.readings, "", today)
    gap = gap_scale(
        [x.log for x in await training.workouts(user_id, today - timedelta(days=60))], today
    )
    wx = await weather.for_user(user_id)
    advice = weather.assess(wx) if wx else None
    poor = state.level == "poor"
    version = build(
        session,
        tired=tired or poor,
        tired_why="你说今天有点累" if tired else "；".join(state.reasons),
        indoor=advice is not None and advice.level in ("indoor", "avoid"),
        indoor_why=advice.reasons[0] if advice and advice.reasons else "",
        minutes=minutes,
        scale=gap[0] if gap else None,
        scale_why=gap[1] if gap else "",
    )
    return {
        "status": "ok",
        "original": session.model_dump(mode="json"),
        "today": version.session.model_dump(mode="json"),
        "changed": version.changed,
        "changes": list(version.changes),
        "reasons": list(version.reasons),
        "readiness": state.name,
    }


# ---- 目标进度与阶段复测（spec [2026-10-23] §18 需求 6）---------------------------------------------


def goal_store() -> Any:
    from ironm_agent.goal import default_goal

    return default_goal()


GOAL = Depends(goal_store)  # 测试时用 dependency_overrides 换成内存版


class GoalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float = Field(ge=30, le=250)  # 目标体重（公斤）
    by: date


async def _goal_state(user_id: str, goals: Any) -> dict[str, Any]:
    from ironm_agent.goal import progress

    g = await goals.get(user_id)
    if g is None:
        return {"goal": None, "progress": None}
    snap = await _web().snapshot_for(user_id)
    trend = next((m for m in snap.metrics if m.key == "weight_trend"), None)
    return {"goal": g.json(), "progress": progress(g, snap.readings.weight, trend, snap.today)}


@router.get("/iron/api/goal")
async def get_goal(user_id: str = Depends(_verify()), goals: Any = GOAL) -> dict[str, Any]:
    return await _goal_state(user_id, goals)


@router.put("/iron/api/goal")
async def put_goal(
    body: GoalIn, user_id: str = Depends(_verify()), goals: Any = GOAL
) -> dict[str, Any]:
    from ironm_agent.goal import Goal

    today = date.today()
    if not today < body.by <= today + timedelta(days=730):
        raise HTTPException(422, "目标日期要在今天之后、两年以内")
    snap = await _web().snapshot_for(user_id)
    weights = sorted(snap.readings.weight)
    old = await goals.get(user_id)
    start = weights[-1][1] if weights else None
    retest_day = old.retest_day if old is not None else None
    await goals.set(user_id, Goal(body.value, body.by, today, start, retest_day))
    coach_later(user_id, "改目标")
    return await _goal_state(user_id, goals)


@router.delete("/iron/api/goal")
async def delete_goal(user_id: str = Depends(_verify()), goals: Any = GOAL) -> dict[str, Any]:
    await goals.clear(user_id)
    coach_later(user_id, "改目标")
    return {"goal": None, "progress": None}


@router.post("/iron/api/goal/retest")
async def goal_retest(user_id: str = Depends(_verify()), goals: Any = GOAL) -> dict[str, Any]:
    """记下今天复测过（体重请照常记录或同步；关键动作在打卡里填每组的重量和次数）。"""
    from ironm_agent.goal import retested

    g = await goals.get(user_id)
    if g is None:
        raise HTTPException(404, "还没有设目标")
    await goals.set(user_id, retested(g, date.today()))
    coach_later(user_id, "复测")
    return await _goal_state(user_id, goals)


# ---- 管家的当前方案与调整经历（spec [2026-10-23] §23）---------------------------------------------


def coach_deps() -> Any:
    """重新评估要读的存储（测试时整个换掉）。"""
    from ironm_agent.coach_state import Deps, default_coach

    return Deps(
        snapshot=_web().snapshot_for,
        training=training_store(),
        pain=pain_store(),
        goals=goal_store(),
        diet=diet_store(),
        store=default_coach(),
        weather=weather.for_user,
    )


def coach_later(user_id: str, reason: str) -> None:
    """有新情况时在后台重新评估当前方案（打卡、记饮食、说疼、改目标、确认或撤销方案）。"""
    from ironm_agent.coach_state import evaluate_later

    try:
        evaluate_later(user_id, coach_deps(), reason)
    except Exception as e:  # 不影响这次请求
        _log.warning("coach schedule failed: error_type=%s", type(e).__name__)


def _coach_json(state: Any, changes: list[Any]) -> dict[str, Any]:
    return {
        "version": state.version,
        "day": state.day.isoformat(),
        "reason": state.reason,
        "items": [x.model_dump(mode="json") for x in state.items],
        "changes": [c.model_dump(mode="json") for c in changes],
        "pending": [x.model_dump(mode="json") for x in state.items if x.action == "confirm"],
    }


@router.get("/iron/api/coach")
async def get_coach(user_id: str = Depends(_verify())) -> dict[str, Any]:
    """管家今日调整：当前方案、今天改了什么、待确认的方案。每天第一次打开时评估一次。"""
    from ironm_agent.coach_state import evaluate

    deps = coach_deps()
    try:
        state, _ = await evaluate(user_id, deps, reason="每天第一次打开", force=False)
    except Exception as e:
        _log.error("coach failed: error_type=%s", type(e).__name__)
        raise HTTPException(503, "管家的方案暂时算不出来，请稍后再试") from e
    order = {
        x.key: i for i, x in enumerate(state.items)
    }  # 按方案里的顺序：今天、提醒、待确认、饮食、目标……
    today = [c for c in await deps.store.history(user_id, 60) if c.day == state.day]
    latest = {c.key: c for c in reversed(today)}  # 同一项今天改了几次只显示最后一次
    shown = sorted(latest.values(), key=lambda c: order.get(c.key, len(order)))
    return _coach_json(state, shown)


@router.get("/iron/api/coach/history")
async def get_coach_history(user_id: str = Depends(_verify())) -> dict[str, Any]:
    deps = coach_deps()
    return {"changes": [c.model_dump(mode="json") for c in await deps.store.history(user_id, 60)]}


class CoachSeen(BaseModel):
    version: int = Field(ge=1)


class CoachDecision(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    decision: Literal["accept", "later"]


@router.get("/iron/api/coach/inbox")
async def coach_inbox(user_id: str = Depends(_verify())) -> dict[str, Any]:
    """对话里的管家消息（spec [2026-10-23] §26）：还没看过的自动调整，以及要用户确认的调整。"""
    from ironm_agent.coach_state import evaluate, pending, unseen

    deps = coach_deps()
    try:
        state, _ = await evaluate(user_id, deps, reason="打开对话", force=False)
    except Exception as e:
        _log.error("coach inbox failed: error_type=%s", type(e).__name__)
        raise HTTPException(503, "管家的方案暂时算不出来，请稍后再试") from e
    news = unseen(state, await deps.store.history(user_id, 60))
    return {
        "version": state.version,
        "changes": [c.model_dump(mode="json") for c in news],
        "pending": [x.model_dump(mode="json") for x in pending(state, date.today())],
    }


@router.post("/iron/api/coach/seen")
async def coach_seen(body: CoachSeen, user_id: str = Depends(_verify())) -> dict[str, Any]:
    from ironm_agent.coach_state import mark_seen

    await mark_seen(coach_deps().store, user_id, body.version)
    return {"seen": body.version}


@router.post("/iron/api/coach/decide")
async def coach_decide(body: CoachDecision, user_id: str = Depends(_verify())) -> dict[str, Any]:
    """用户在对话里确认或暂不一条调整；确认后的执行（调热量、生成计划预览）由页面接着调对应接口。"""
    from ironm_agent.coach_state import decide

    item = await decide(coach_deps().store, user_id, body.key, body.decision)
    if item is None:
        raise HTTPException(404, "这条调整已经不需要处理了")
    return {"key": body.key, "decision": body.decision, "item": item.model_dump(mode="json")}


# ---- 自己记一条、改值、删一条（spec [2026-10-23] §26 需求 4）-----------------------------------------


def reading_store() -> Any:
    from ironm_agent.readings import default_readings

    return default_readings()


READINGS = Depends(reading_store)  # 测试时用 dependency_overrides 换成内存版


class ReadingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    value: float
    day: date | None = None


class ReadingFix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float


def _reading_kind(kind: str) -> Any:
    from ironm_agent.readings import KINDS

    if kind not in KINDS:
        raise HTTPException(422, "这项数据不能手动记录")
    return KINDS[kind]


@router.get("/iron/api/readings")
async def get_readings(
    kind: str, user_id: str = Depends(_verify()), store: Any = READINGS
) -> dict[str, Any]:
    k = _reading_kind(kind)
    rows = await store.recent(user_id, kind)
    return {
        "kind": kind,
        "title": k.title,
        "unit": k.shown,
        "low": k.low,
        "high": k.high,
        "rows": rows,
    }


@router.post("/iron/api/readings")
async def add_reading(
    body: ReadingIn, user_id: str = Depends(_verify()), store: Any = READINGS
) -> dict[str, Any]:
    from ironm_agent.readings import OutOfRange, check

    _reading_kind(body.kind)
    day = body.day or date.today()
    if day > date.today() or (date.today() - day).days > 365:
        raise HTTPException(422, "日期只能是今天或一年以内")
    try:
        check(body.kind, body.value)
    except OutOfRange as e:
        raise HTTPException(422, str(e)) from e
    if await store.add(user_id, body.kind, body.value, day) < 1:
        raise HTTPException(409, "同一天已经记过同样的数，没有重复写入")
    coach_later(user_id, "记数据")
    return {"ok": True, "rows": await store.recent(user_id, body.kind)}


@router.post("/iron/api/readings/{kind}/{row_id}")
async def fix_reading(
    kind: str,
    row_id: int,
    body: ReadingFix,
    user_id: str = Depends(_verify()),
    store: Any = READINGS,
) -> dict[str, Any]:
    from ironm_agent.readings import OutOfRange, check

    _reading_kind(kind)
    try:
        check(kind, body.value)
    except OutOfRange as e:
        raise HTTPException(422, str(e)) from e
    if not await store.amend(user_id, row_id, body.value):
        raise HTTPException(404, "这条记录不存在")
    coach_later(user_id, "记数据")
    return {"ok": True, "rows": await store.recent(user_id, kind)}


@router.delete("/iron/api/readings/{kind}/{row_id}")
async def delete_reading(
    kind: str, row_id: int, user_id: str = Depends(_verify()), store: Any = READINGS
) -> dict[str, Any]:
    _reading_kind(kind)
    if not await store.remove(user_id, row_id):
        raise HTTPException(404, "这条记录不存在")
    coach_later(user_id, "记数据")
    return {"ok": True, "rows": await store.recent(user_id, kind)}


# ---- 运行框架（spec [2026-10-23] §31）：评价记到那一轮、系统汇总、个人汇总 ------------------------------


def trace_store() -> Any:
    from ironm_agent.harness import default_traces

    return default_traces()


TRACES = Depends(trace_store)  # 测试时用 dependency_overrides 换成内存版


class RatingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rating: Literal[1, -1]


@router.post("/iron/api/turns/{turn_id}/rating")
async def rate_turn(
    turn_id: str, body: RatingIn, user_id: str = Depends(_verify()), store: Any = TRACES
) -> dict[str, Any]:
    """页面上点"有用 / 没用"：记到这一轮的轨迹上；只能评自己的那一轮。"""
    from ironm_agent.harness import rate

    if not await rate(store, user_id, turn_id, body.rating):
        raise HTTPException(404, "找不到这一轮")
    return {"ok": True}


async def _admin_only(user_id: str) -> None:
    if not await is_admin(user_id):
        raise HTTPException(403, "只有管理员能查看")


def _since(days: int) -> Any:
    from datetime import UTC, datetime

    return datetime.now(UTC) - timedelta(days=max(1, min(180, days)))


@router.get("/iron/api/admin/harness/system")
async def harness_system(
    days: int = 7, user_id: str = Depends(_verify()), store: Any = TRACES
) -> dict[str, Any]:
    """系统汇总：按环节、按专业 Agent、按 Skill、按工具的出错次数和比例，耗时（只给管理员）。"""
    from ironm_agent.harness import system_summary

    await _admin_only(user_id)
    return {"days": days, **system_summary(await store.since(_since(days)))}


@router.get("/iron/api/admin/harness/person/{person}")
async def harness_person(
    person: str, days: int = 30, user_id: str = Depends(_verify()), store: Any = TRACES
) -> dict[str, Any]:
    """个人汇总：系统在这个人身上哪里没帮好（只给管理员）。"""
    from ironm_agent.harness import person_summary

    await _admin_only(user_id)
    start = _since(days)
    try:
        changes = await coach_deps().store.history(person, 200)
        declined = sum(1 for c in changes if c.change == "declined" and c.day >= start.date())
    except Exception as e:  # 读不到调整经历不影响其余汇总
        _log.warning("coach history failed: error_type=%s", type(e).__name__)
        declined = 0
    return {"days": days, **person_summary(await store.since(start, person), declined)}


@router.get("/iron/api/admin/harness/turns")
async def harness_turns(
    days: int = 1,
    person: str = "",
    bad: bool = True,
    limit: int = 50,
    user_id: str = Depends(_verify()),
    store: Any = TRACES,
) -> dict[str, Any]:
    """逐轮看哪里出错：每一轮的时间、路径、耗时、请了谁、用了哪些 Skill、出错信号（只给管理员，不含内容）。"""
    from ironm_agent.harness import turn_brief

    await _admin_only(user_id)
    turns = await store.since(_since(days), person or None)
    rows = [turn_brief(t) for t in reversed(turns)]
    if bad:
        rows = [r for r in rows if r["signals"]]
    return {"turns": rows[: max(1, min(200, limit))]}


# ---- 本周计划和天气（spec [2026-10-23] §34）---------------------------------------------------


@router.get("/iron/api/week")
async def get_week(
    user_id: str = Depends(_verify()), training: TrainingStore = TRAINING
) -> dict[str, Any]:
    """本周一到周日：每天练什么、练过没有、天气和对训练的影响、按天气改出的版本（原计划不变）。"""
    from ironm_agent.weather_plan import week_plan, weekday

    today = date.today()
    monday = today - timedelta(days=today.isoweekday() - 1)
    stored = await training.plan(user_id)
    done = {x.log.day for x in await training.workouts(user_id, monday) if x.log.done}
    status, wx = "no_city", None
    try:
        _, place = await weather.load_place(user_id)
        if place is not None:
            wx = await weather.safe_fetch(place)
            status = "ok" if wx is not None else "unavailable"
    except Exception as e:
        _log.warning("week weather unavailable: error_type=%s", type(e).__name__)
        status = "unavailable"
    now = weather.assess(wx) if wx is not None else None
    days = week_plan(stored.plan if stored else None, wx.days if wx else (), today, now)

    def wx_json(p: Any) -> dict[str, Any] | None:
        if p.day == today and wx is not None and now is not None:
            return {"text": wx.text, "temp": round(wx.temperature), "feels_like": round(wx.feels_like),
                    "tmin": round(p.weather.tmin) if p.weather else None,
                    "tmax": round(p.weather.tmax) if p.weather else None, "rain": p.weather.rain if p.weather else None,
                    "aqi_level": weather.aqi_level(wx.aqi)[0] if wx.aqi is not None else None,
                    "level": now.level, "name": now.name, "reasons": list(now.reasons), "live": True}  # fmt: skip
        if p.weather is None or p.advice is None:
            return None
        return {"text": p.weather.text, "temp": round(p.weather.tmax), "tmin": round(p.weather.tmin),
                "tmax": round(p.weather.tmax), "rain": p.weather.rain, "level": p.advice.level,
                "name": p.advice.name, "reasons": list(p.advice.reasons), "live": False}  # fmt: skip

    return {
        "weather": status,
        "place": wx.place if wx is not None else "",
        "days": [
            {
                "date": p.day.isoformat(),
                "weekday": weekday(p.day),
                "today": p.day == today,
                "past": p.day < today,
                "done": p.day in done,
                "session": p.session.model_dump(mode="json") if p.session else None,
                "version": p.version.model_dump(mode="json") if p.version else None,
                "changes": list(p.changes),
                "reasons": list(p.reasons),
                "outdoor": list(p.outdoor),
                "better": weekday(p.better) if p.better else "",
                "weather": wx_json(p),
            }
            for p in days
        ],
    }
