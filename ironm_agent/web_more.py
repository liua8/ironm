"""前端改版用到的接口（spec [2026-10-23] §13）：城市与天气、训练日历、肌肉人体图、动作视频、饮食记录与推荐。

挂在 web.router 上（同一个服务、同一套登录）；只读写 iron-m 自己的表和文件，不改 mirobody。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from ironm_agent import spoken as spoken_mod
from ironm_agent import weather
from ironm_agent.exercises import library
from ironm_agent.llm import TurnLLM, load_models
from ironm_agent.meals import (
    MAX_PHOTO_BYTES,
    MEAL_KINDS,
    Appetite,
    DayContext,
    Macros,
    Meal,
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
from ironm_agent.plan_edit import apply_today, with_today
from ironm_agent.protools.muscle_map import muscle_map
from ironm_agent.training import TrainingStore, week_start

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


def photo_store() -> Any:
    from ironm_agent.checkin_photo import default_photos

    return default_photos()


def video_dir() -> Path:
    """动作视频放在本机的数据目录（不进仓库）。"""
    return Path(os.environ.get("IRONM_DATA_DIR") or ROOT / "data") / "videos"


TRAINING = Depends(training_store)
MEMORY = Depends(memory_store)
MEALS = Depends(meal_store)  # 测试时用 dependency_overrides 换成内存版
PHOTOS = Depends(photo_store)  # 打卡照片（§117），测试时换成内存版
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


def illness_store() -> Any:
    from ironm_agent.illness import default_illness

    return default_illness()


ILLNESS = Depends(illness_store)  # 生病记录（spec [2026-10-23] §46）；测试时换成内存版


def checkin_streak(days: set[date], today: date) -> int:
    """连续打卡天数（§105）：从今天往前数；今天还没打卡从昨天数。"""
    d = today if today in days else today - timedelta(days=1)
    n = 0
    while d in days:
        n += 1
        d -= timedelta(days=1)
    return n


@router.get("/iron/api/calendar")
async def get_calendar(
    month: str = "",
    user_id: str = Depends(_verify()),
    store: TrainingStore = TRAINING,
    illness: Any = ILLNESS,
) -> dict[str, Any]:
    """整月的训练记录，加上首页战报的本月、本周统计（spec [2026-10-23] §64）。"""
    from ironm_agent.illness import sick_days
    from ironm_agent.report import history_start, report

    today = date.today()
    if month and not _MONTH.match(month):
        raise HTTPException(422, "月份写成 2026-10 这样")
    first = date.fromisoformat(f"{month}-01") if month else today.replace(day=1)
    nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    since = min(history_start(first), week_start(today))
    rows = await store.workouts(user_id, since)
    sick: frozenset[date] = frozenset()
    try:  # 生病记录读不到时照样出战报（生病的日子当作应练）
        sick = sick_days(await illness.since(user_id, since), today)
    except Exception as e:
        _log.warning("calendar illness unavailable: error_type=%s", type(e).__name__)
    stats = report(await store.plans(user_id), [x.log for x in rows], first, today, sick)
    days: dict[str, list[dict[str, Any]]] = {}
    for x in sorted(rows, key=lambda r: r.log.day):
        if not first <= x.log.day < nxt:
            continue
        days.setdefault(x.log.day.isoformat(), []).append(
            {
                "id": x.id,
                "done": x.log.done,
                "session": x.log.session,
                "rpe": x.log.rpe,
                "line": x.log.line(),
                "rest": x.log.rest,
            }
        )
    # 轨迹（§105）：每天做的组数（月历分深浅；没填每组的按计划组数算）、本月一共练了多久、
    # 连续打卡天数（练了或记了没练都算）
    count: Counter[date] = Counter()
    for x in rows:
        if x.log.done and first <= x.log.day < nxt:
            count[x.log.day] += sum(len(it.done_sets) or it.sets or 0 for it in x.log.items)
    sets = {d.isoformat(): n for d, n in count.items() if n}
    month_minutes = sum(x.log.minutes or 0 for x in rows if x.log.done and first <= x.log.day < nxt)
    return {
        "month": first.strftime("%Y-%m"),
        "today": today.isoformat(),
        "days": days,
        "done_days": sorted(d for d, v in days.items() if any(e["done"] for e in v)),
        "rest_days": sorted(
            d
            for d, v in days.items()
            if any(e["rest"] for e in v) and not any(e["done"] for e in v)
        ),
        "sets": sets,
        "month_minutes": month_minutes,
        "streak_days": checkin_streak({x.log.day for x in rows if x.log.done or x.log.rest}, today),
        **stats,
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
    logs = [x.log for x in await store.workouts(user_id, today - timedelta(days=45))]
    return muscle_map(logs, today, plan.plan if plan else None, await feel.latest(user_id),
                      now=datetime.now(), rates=await feel.rates(user_id))  # fmt: skip


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
    from ironm_agent.protools.fatigue import calibrate
    from ironm_agent.protools.muscle_map import MUSCLES

    if body.muscle not in MUSCLES:
        raise HTTPException(422, "没有这块肌肉")
    # 他说的和算的恢复度对不上时，调这块肌肉在他身上的恢复快慢（§70 修改）
    now = await get_muscles(user_id, store, feel)
    pct = next(int(m["recovery"]) for m in now["muscles"] if m["code"] == body.muscle)
    rate = (await feel.rates(user_id)).get(body.muscle, 1.0)
    if (new := calibrate(rate, pct, body.feel)) is not None:
        await feel.set_rate(user_id, body.muscle, new)
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
        raise HTTPException(422, f"餐次只能是{'、'.join(MEAL_KINDS)}")
    return kind


async def _save_meal(
    store: MealStore, user_id: str, meal: Meal, photo: bytes | None = None, mime: str = ""
) -> dict[str, Any]:
    """存下这一餐，再删掉今天同一种餐原来的记录：每种餐每天只留一份（spec [2026-10-23] §43）。
    先存后删，存不上时原来那条还在。"""
    row = await store.add(user_id, date.today(), meal, photo, mime)
    replaced = []
    for old in await store.day(user_id, row.day):
        if old.id != row.id and old.meal.kind == meal.kind and await store.delete(user_id, old.id):
            replaced.append(old.meal.name)
    coach_later(user_id, "记饮食")
    return {"meal": row.json(), "replaced": replaced, **(await _day_json(user_id, row.day, store))}


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
    _log.info("meal added: photo=%s", data is not None)
    return await _save_meal(store, user_id, meal, data, mime)


class PresetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset: str = Field(min_length=1, max_length=40)
    kind: str = "午餐"


@router.get("/iron/api/meals/presets")
async def get_presets(user_id: str = Depends(_verify())) -> dict[str, Any]:
    from ironm_agent.food_images import image_for

    return {
        "presets": [{**p.model_dump(), "image": image_for(f"preset:{p.id}")} for p in presets()],
        "note": "按常见分量估算，实际随做法和分量变化（内容待审定）",
    }


@router.post("/iron/api/meals/preset")
async def add_preset(
    body: PresetIn, user_id: str = Depends(_verify()), store: MealStore = MEALS
) -> dict[str, Any]:
    found = next((p for p in presets() if p.id == body.preset), None)
    if found is None:
        raise HTTPException(404, "没有这个减脂餐")
    return await _save_meal(store, user_id, preset_meal(found, _kind(body.kind)))


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
    meal = Meal(
        kind=_kind(body.kind),
        name=body.name,
        items=[x[:40] for x in body.items],
        macros=body.macros.rounded(),
        note="按推荐记下，营养是估算的",
    )
    return await _save_meal(store, user_id, meal)


# ---- 每周复盘直接出调整方案（spec [2026-10-23] §18 需求 1）---------------------------------------


def make_agent(training: TrainingStore, memory: MemoryStore) -> Any:
    """生成调整方案用的 Agent：和对话里改计划走同一条链路（测试时换成假的）。"""
    from ironm_agent.plugin import IronMAgent

    agent = IronMAgent(training=training, memory=memory)
    agent._remember_on = False  # 这不是用户说的话，不提取记忆
    return agent


# ---- 触发型调整（spec [2026-10-23] §18 需求 5）---------------------------------------------------

TRIGGER_ASK = "按首页的提醒调整训练计划"


def day_store() -> Any:
    from ironm_agent.day_state import default_day

    return default_day()


DAY = Depends(day_store)  # 今日状态（spec [2026-10-23] §54）；测试时换成内存版


async def _episodes(illness: Any, user_id: str, today: date) -> list[Any]:
    from ironm_agent.illness import recent

    return await recent(illness, user_id, today)


def pain_store() -> Any:
    from ironm_agent.triggers import default_pain

    return default_pain()


PAIN = Depends(pain_store)  # 测试时用 dependency_overrides 换成内存版


async def _triggers(
    user_id: str, training: TrainingStore, pain: Any, today: date, illness: Any = None, memory: Any = None
) -> list[Any]:
    from ironm_agent.illness import sick_days
    from ironm_agent.triggers import PAIN_DAYS, PLATEAU_LOOKBACK, detect

    stored = await training.plan(user_id)
    logs = [
        x.log for x in await training.workouts(user_id, today - timedelta(days=PLATEAU_LOOKBACK))
    ]
    pains = await pain.since(user_id, today - timedelta(days=PAIN_DAYS))
    if memory is not None:  # 说好了的那处，之前的疼不再算（§158）
        from ironm_agent.body_now import fresh

        try:
            pains = fresh(pains, await memory.items(user_id))
        except Exception as e:
            _log.info("memory unavailable for triggers: error_type=%s", type(e).__name__)
    eps = await _episodes(illness, user_id, today) if illness is not None else []
    return detect(
        stored.plan if stored else None, logs, stored.since if stored else None, pains, today,
        sick_days(eps, today),
    )  # fmt: skip


@router.get("/iron/api/triggers")
async def get_triggers(
    user_id: str = Depends(_verify()),
    training: TrainingStore = TRAINING,
    pain: Any = PAIN,
    illness: Any = ILLNESS,
    memory: MemoryStore = MEMORY,
) -> dict[str, Any]:
    found = await _triggers(user_id, training, pain, date.today(), illness, memory)
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
    illness: Any = ILLNESS,
) -> dict[str, Any]:
    """按每周复盘（或首页的某条提醒，trigger 为提醒的种类）生成调整方案；提醒在服务端重新判断。"""
    from ironm_agent.brief import weekly_review
    from ironm_agent.illness import recurring, sick_days
    from ironm_agent.plugin import REVIEW_ASK, REVIEW_MAX_DAYS
    from ironm_agent.protools.plan_check import changed_days
    from ironm_agent.training import parse_plan

    stored = await training.plan(user_id)
    if stored is None:
        raise HTTPException(409, "还没有训练计划：先让教练排一份")
    if not trigger and (ready := await _checkup_proposal(user_id, training)) is not None:
        return ready  # 每日复查提的改计划：已经存成预览，直接给他看（§129 需求 3）
    snap = await _web().snapshot_for(user_id)
    if trigger:
        found = await _triggers(user_id, training, pain, snap.today, illness, memory)
        hit = next((t for t in found if t.kind == trigger and t.action == "proposal"), None)
        if hit is None:
            return {"status": "no_change", "message": "这条提醒已经不需要处理了。"}
        tips = [hit.tip]
        actions = _trigger_actions(hit, stored.plan)
        ask = f"{TRIGGER_ASK}（只改需要改的地方）：{hit.tip}"
    else:
        logs = [x.log for x in await training.workouts(user_id, snap.today - timedelta(days=14))]
        eps = await _episodes(illness, user_id, snap.today)
        review = weekly_review(snap, stored.plan, logs, stored.since, sick=sick_days(eps, snap.today),
                               sick_times=recurring(eps, snap.today))  # fmt: skip
        tips, actions = review["tips"], list(review.get("actions") or [])
        if not tips:
            return {"status": "no_change", "message": "这周没有需要调整的地方，照计划来。"}
        ask = f"{REVIEW_ASK}（每次最多改两处，只改需要改的地方）：" + "".join(tips)
    ruled = await _rule_proposal(user_id, actions, stored.plan, training, memory, trigger, tips)
    if ruled is not None:  # 复盘和提醒能变成固定操作的：规则直接改，不调用模型（§45）
        return ruled
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


async def _checkup_proposal(user_id: str, training: TrainingStore) -> dict[str, Any] | None:
    """今天的复查提了改计划、预览还没确认：把那份预览交给页面（不再重新生成）。"""
    try:
        state = await coach_deps().store.get(user_id)
    except Exception as e:
        _log.warning("coach state unavailable: error_type=%s", type(e).__name__)
        return None
    review = state.review if state is not None else None
    if review is None or review.day != date.today():
        return None
    d = next((x for x in review.done if x.type == "propose" and not x.undone), None)
    draft = await training.draft(user_id, str(d.value.get("draft"))) if d is not None else None
    if d is None:
        return None
    if (
        draft is None or draft.state != "pending"
    ):  # 确认过、作废了或过期了：不再生成另一份（复核 11-03）
        return {"status": "no_change", "message": "这条建议已经处理过了；想再调可以直接告诉我。"}
    stored = await training.plan(user_id)
    if stored is None or draft.content.get("base") != stored.id:  # 计划后来改过：这份预览过时了
        from ironm_agent.review import undo

        await undo(user_id, coach_deps(), d.key, today=review.day)  # 作废预览，这条待确认也一并收起
        return {
            "status": "no_change",
            "message": "计划后来改过了，这条建议不再适用；想再调可以直接告诉我。",
        }
    return {"status": "ok", "tips": [d.why], "answer": f"{d.title}。{d.why}", "draft": draft.json(),
            "changed_days": 0, "warning": ""}  # fmt: skip


def _trigger_actions(hit: Any, plan: Any) -> list[dict[str, Any]]:
    """首页提醒对应的调整：反复疼换掉压这个部位的动作，连续没练少一天或减量，平台期换变式。"""
    if hit.kind == "pain" and hit.part:
        return [{"kind": "swap_part", "part": hit.part, "why": hit.title}]
    if hit.kind == "missed":
        kind = "fewer_days" if plan.days_per_week > 2 else "lighter"
        return [{"kind": kind, "days": plan.days_per_week - 1, "why": hit.title}]
    if hit.kind == "plateau" and hit.exercises:
        return [{"kind": "variant", "exercises": list(hit.exercises), "why": hit.title}]
    return []


async def _rule_proposal(
    user_id: str,
    actions: list[dict[str, Any]],
    plan: Any,
    training: TrainingStore,
    memory: MemoryStore,
    trigger: str,
    tips: list[str],
) -> dict[str, Any] | None:
    """按规则生成操作、由代码改计划（spec [2026-10-23] §45）；变不成操作或一条都套不上时返回 None。"""
    from ironm_agent.casefile import injured_parts
    from ironm_agent.constraints import Context, annotate_plan
    from ironm_agent.facts import equipment as equipment_in
    from ironm_agent.memory_view import Recall
    from ironm_agent.plan_ops import apply, describe, fit_time, review_ops
    from ironm_agent.protools.plan_check import changed_days
    from ironm_agent.training import plan_content

    if not actions:
        return None
    try:
        items = Recall.of(await memory.items(user_id)).items
    except Exception as e:  # 读不到记忆：当作不知道器械和伤病
        _log.warning("memory unavailable: error_type=%s", type(e).__name__)
        items = ()
    injured = injured_parts(items, "")
    equipment = equipment_in(items)  # 读字段（§150）
    ops = review_ops(actions, plan, equipment=equipment, injured=injured)
    if not ops:
        return None
    applied = fit_time(apply(plan, ops, equipment=equipment, injured=injured))
    if not applied.done:
        return None
    new = annotate_plan(applied.plan, Context(injuries=tuple(injured)))
    extra = describe(applied)
    draft = await training.add_draft(
        user_id,
        "plan",
        plan_content(new, applied.changes, ops=extra["ops"], skipped=extra["skipped"]),
    )
    _log.info("rule proposal: ops=%d skipped=%d", len(applied.done), len(applied.skipped))
    where = "首页的提醒" if trigger else "这周的复盘"
    return {
        "status": "ok",
        "tips": tips,
        "answer": f"按{where}改了：" + "；".join(applied.lines) + "。",
        "draft": draft.json(),
        "changed_days": changed_days(new, plan),
        "warning": "",
        "by": "rule",
    }


# ---- 两周饮食复盘（spec [2026-10-23] §18 需求 2）------------------------------------------------


def diet_store() -> Any:
    from ironm_agent.diet_adjust import default_diet

    return default_diet()


DIET = Depends(diet_store)  # 测试时用 dependency_overrides 换成内存版


async def _seen(user_id: str, snap: Any, meals: MealStore) -> tuple[Any, str]:
    """按记的吃和体重变化估的每天实际消耗（§118 需求 7）；读不到饮食记录当作条件不够。"""
    from ironm_agent.diet_adjust import OBSERVE_DAYS, by_day, observed

    try:
        rows = await meals.since(user_id, snap.today - timedelta(days=OBSERVE_DAYS - 1))
    except Exception as e:
        _log.warning("meals unavailable: error_type=%s", type(e).__name__)
        return None, "饮食记录这次没读到"
    return observed(by_day(rows), snap.readings.weight, snap.today)


async def _diet_state(user_id: str, diet: Any, meals: MealStore) -> dict[str, Any]:
    from ironm_agent.diet_adjust import propose

    snap = await _web().snapshot_for(user_id)
    current = await diet.current(user_id)
    seen, lack = await _seen(user_id, snap, meals)
    proposal, why = propose(snap.metrics, snap.profile, current, snap.today, seen)
    target = next((m for m in snap.metrics if m.key == "kcal_target"), None)
    formula = next((m for m in snap.metrics if m.key == "tdee"), None)
    return {
        "observed": {
            "tdee": seen.tdee,
            "intake": seen.intake,
            "kg_per_week": seen.kg_per_week,
            "days": seen.days,
            "weighins": seen.weighins,
            "formula": round(formula.value) if formula and formula.value else None,
            "how": "最近两周记了的那些天平均每天吃的 − 体重每天的变化 × 7700 千卡（每公斤约 7700 千卡是粗算）；"
            "有的餐没记，算出来会偏低",
        }
        if seen
        else None,
        "observed_lack": lack,
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
async def diet_review(
    user_id: str = Depends(_verify()), diet: Any = DIET, meals: MealStore = MEALS
) -> dict[str, Any]:
    return await _diet_state(user_id, diet, meals)


@router.post("/iron/api/diet/adjust")
async def diet_apply(
    user_id: str = Depends(_verify()), diet: Any = DIET, meals: MealStore = MEALS
) -> dict[str, Any]:
    """确认调整：服务端按当前数据重新算一遍方案再保存（不信任页面传来的数字）。"""
    from ironm_agent.diet_adjust import propose
    from ironm_agent.metrics import KcalAdjust

    snap = await _web().snapshot_for(user_id)
    seen, _ = await _seen(user_id, snap, meals)
    proposal, why = propose(
        snap.metrics, snap.profile, await diet.current(user_id), snap.today, seen
    )
    if proposal is None:
        raise HTTPException(409, why or "这次不需要调整")
    await diet.apply(user_id, KcalAdjust(proposal.total, snap.today, proposal.reason))
    _log.info("diet adjusted: delta=%d", proposal.delta)
    coach_later(user_id, "确认方案")
    return await _diet_state(user_id, diet, meals)


@router.post("/iron/api/diet/adjust/undo")
async def diet_undo(
    user_id: str = Depends(_verify()), diet: Any = DIET, meals: MealStore = MEALS
) -> dict[str, Any]:
    if await diet.current(user_id) is None:
        raise HTTPException(404, "现在没有热量调整")
    await diet.undo(user_id)
    coach_later(user_id, "撤销方案")
    return await _diet_state(user_id, diet, meals)


# ---- 生病追问（spec [2026-10-23] §46）-----------------------------------------------------------


class CheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: Literal["resolved", "better", "unwell"]


@router.post("/iron/api/illness/{episode_id}/check")
async def illness_check(
    episode_id: str, body: CheckIn, user_id: str = Depends(_verify()), illness: Any = ILLNESS
) -> dict[str, Any]:
    """首页"好些了吗"的按钮：好了 / 好一些 / 还不舒服。状态由规则更新；回给他的话由模型说，
    没说到今天怎么安排（休息、轻松版、七成、看医生）或模型失败时用规则的那句（spec [2026-10-23] §86）。"""
    from ironm_agent.casefile import readiness
    from ironm_agent.illness import answer

    today = date.today()
    eps = await _episodes(illness, user_id, today)
    ep = next((e for e in eps if e.id == episode_id), None)
    if ep is None:
        raise HTTPException(404, "这条记录不存在")
    hr_poor = False
    if body.answer == "resolved":  # 说好了也看一眼心率（§46 需求 4）
        try:
            snap = await _web().snapshot_for(user_id)
            hr_poor = readiness(snap.readings, "", today).level == "poor"
        except Exception as e:
            _log.warning("check snapshot unavailable: error_type=%s", type(e).__name__)
    ep, message = answer(ep, body.answer, today, hr_poor=hr_poor)
    await illness.save(user_id, ep)
    reply = {"resolved": "好了", "better": "好一些了", "unwell": "还不舒服"}[body.answer]
    needs = [w for w in ("休息", "轻松", "七成", "医生") if w in message]
    spoken = await spoken_mod.say(
        spoken_mod.default_llm(), spoken_mod.ILLNESS, f"系统定好的：{message}",
        f"{ep.what()}，今天{reply}", needs,
    )  # fmt: skip
    message = spoken or message
    coach_later(user_id, "身体状况")
    return {"message": message, "status": ep.status}


# ---- 今天的版本（spec [2026-10-23] §18 需求 3）---------------------------------------------------


@router.get("/iron/api/today")
async def get_today(
    minutes: int | None = None,
    tired: bool = False,
    user_id: str = Depends(_verify()),
    training: TrainingStore = TRAINING,
    illness: Any = ILLNESS,
    day: Any = DAY,
) -> dict[str, Any]:
    """今天的版本：和管家消息里的"今天"同一个算法（§97：生病、管家复盘、今天说过的累和可用时间、
    天气、中断后降量、状态差）；原计划不变。首页点了"有点累""只有 N 分钟"先写进今日状态（§54）。"""
    from ironm_agent.coach_state import Inputs, today_version

    if minutes is not None and not 10 <= minutes <= 180:
        raise HTTPException(422, "可用时间要在 10 到 180 分钟之间")
    stored = await training.plan(user_id)
    today = date.today()
    if stored is None:
        return {"status": "no_plan"}
    if stored.plan.session_on(today) is None:
        return {"status": "rest"}
    said, _ = await _day_said(day, user_id, today, tired=tired, minutes=minutes)
    snap = await _web().snapshot_for(user_id)
    wx = await weather.for_user(user_id)
    inp = Inputs(snapshot=snap, plan=stored.plan, since=stored.since,
                 logs=[x.log for x in await training.workouts(user_id, today - timedelta(days=60))],
                 illness=await _episodes(illness, user_id, today), day=said,
                 advice=weather.assess(wx) if wx else None, review=await review_today(user_id))  # fmt: skip
    v = today_version(inp, today, tired=tired, minutes=minutes)
    if v.status in ("sick", "review_rest"):  # 生病还没好、管家复盘定了今天休息
        return {"status": "sick" if v.status == "sick" else "rest_today", "original": v.original,
                "message": v.title}  # fmt: skip
    return {"status": "ok", "original": v.original, "today": v.today, "changed": v.changed,
            "changes": list(v.changes), "reasons": list(v.reasons), "readiness": v.readiness}  # fmt: skip


async def review_today(user_id: str) -> Any:
    """管家今天的复盘（§85），首页、训练中都按它；读不到当作没有（测试里换掉）。"""
    try:
        state = await asyncio.wait_for(coach_deps().store.get(user_id), 3)
    except Exception as e:
        _log.info("coach review unavailable: error_type=%s", type(e).__name__)
        return None
    review = state.review if state is not None else None
    return review if review is not None and review.day == date.today() else None


async def _day_said(
    day: Any, user_id: str, today: date, *, tired: bool, minutes: int | None
) -> tuple[Any, str]:
    """首页点的写进今日状态；返回（今日状态, 今天说过累或没睡好时的说明）。读写失败当作没有。"""
    from datetime import UTC, datetime

    from ironm_agent.day_state import Entry

    now = datetime.now(UTC)
    new = [Entry(kind="tired", at=now, source="home")] if tired else []
    if minutes is not None:
        new.append(Entry(kind="minutes", at=now, source="home", minutes=minutes))
    try:
        state = await day.add(user_id, today, new) if new else await day.get(user_id, today)
    except Exception as e:
        _log.warning("day state unavailable: error_type=%s", type(e).__name__)
        return None, ""
    bad = state.tired() if state is not None else None
    return state, bad.text() if bad is not None else ""


# ---- 目标进度与阶段复测（spec [2026-10-23] §18 需求 6）---------------------------------------------


def goal_store() -> Any:
    from ironm_agent.goal import default_goal

    return default_goal()


GOAL = Depends(goal_store)  # 测试时用 dependency_overrides 换成内存版


class GoalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float = Field(ge=30, le=250)  # 目标体重（公斤）
    by: date


def _old_goal_memories(items: Any, kind: str) -> list[list[str]]:
    """记忆里说目标方向、和新方向不一样的"目标"条和它原来的状态（确认改目标后作废，免得管家同时看到两个方向）。"""
    from ironm_agent.plugin import _GOAL_WORDS, _said_goal

    return [[x.id, x.status] for x in items if x.category == "goal" and x.status in ("active", "pending")
            and not _said_goal(kind, x.content)
            and any(_said_goal(k, x.content) for k in _GOAL_WORDS if k != kind)]  # fmt: skip


async def apply_goal(
    user_id: str, draft: dict[str, Any], goals: Any, store: Any = None, memory: Any = None
) -> None:
    """改目标的预览确认了（§151）：改档案的目标类型、目标表，管家重新评估。
    先记下确认这一刻的目标（出卡片到确认之间他可能在目标页又改过），撤销时恢复到这个。
    要读的都先读完再写；写到一半出错，把已写的恢复回去再报错（复核 11-03）。"""
    from ironm_agent import profile as profiles
    from ironm_agent.goal import Goal
    from ironm_agent.memory_store import Change

    after = draft.get("goal") or {}
    old_goal = await goals.get(user_id)
    before: dict[str, Any] = {
        "type": (await profiles.load(user_id))[0].goal,
        "goal": old_goal.json() if old_goal else None,
    }
    new_goal = None
    if after.get("value") is not None and after.get("by"):
        snap = await _web().snapshot_for(user_id)
        weights = sorted(snap.readings.weight)
        start = weights[-1][1] if weights else None
        new_goal = Goal(float(after["value"]), date.fromisoformat(after["by"]), date.today(),
                        start, old_goal.retest_day if old_goal is not None else None)  # fmt: skip
    if memory is not None and after.get("type"):
        before["memory"] = _old_goal_memories(await memory.items(user_id), str(after["type"]))
    if store is not None and draft.get("id"):
        content = {k: v for k, v in draft.items()
                   if k not in ("id", "kind", "state", "expired", "created", "expires")}  # fmt: skip
        await store.amend(user_id, str(draft["id"]), {**content, "before": before})
    try:
        if after.get("type"):
            await profiles.set_goal(user_id, str(after["type"]))
        if new_goal is not None:
            await goals.set(user_id, new_goal)
        if memory is not None and before.get("memory"):
            await memory.apply(user_id, [Change("status", id=x, status="superseded") for x, _ in before["memory"]])
    except Exception:
        try:
            await restore_goal(user_id, {"goal": after, "before": before}, goals, memory, wake=False)
        except Exception as e:
            _log.warning("goal restore failed: error_type=%s", type(e).__name__)
        raise
    coach_later(user_id, "改目标")


async def goal_unchanged(user_id: str, draft: dict[str, Any], goals: Any) -> bool:
    """确认之后目标没再被改过（撤销前看，之后又改过就不能撤销这一次）。"""
    from ironm_agent import profile as profiles

    after = draft.get("goal") or {}
    if after.get("type") and (await profiles.load(user_id))[0].goal != after["type"]:
        return False
    if after.get("value") is not None:
        g = await goals.get(user_id)
        if g is None or g.value != float(after["value"]) or g.by.isoformat() != after.get("by"):
            return False
    return True


async def restore_goal(
    user_id: str, draft: dict[str, Any], goals: Any, memory: Any = None, *, wake: bool = True
) -> None:
    """撤销改目标：档案的目标类型、目标表、作废的旧"目标"记忆恢复成确认前的样子，管家重新评估。"""
    from ironm_agent import profile as profiles
    from ironm_agent.goal import Goal
    from ironm_agent.memory_store import Change

    after, before = draft.get("goal") or {}, draft.get("before") or {}
    if after.get("type"):
        await profiles.set_goal(user_id, before.get("type"))
    if after.get("value") is not None:
        if before.get("goal"):
            await goals.set(user_id, Goal.of(before["goal"]))
        else:
            await goals.clear(user_id)
    if memory is not None and before.get("memory"):
        await memory.apply(user_id, [Change("status", id=x, status=was) for x, was in before["memory"]])
    if wake:
        coach_later(user_id, "撤销改目标")


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


@router.post("/iron/api/goal/celebrated")
async def goal_celebrated(user_id: str = Depends(_verify()), goals: Any = GOAL) -> dict[str, Any]:
    """达到目标的庆祝看过了（§93）：记下来，之后再打开不再放彩带。"""
    from dataclasses import replace

    g = await goals.get(user_id)
    if g is not None and g.celebrated is None:
        await goals.set(user_id, replace(g, celebrated=date.today()))
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
        illness=illness_store(),
        day=day_store(),
        memory=_web().memory_store(),
        meals=meal_store(),
    )


def plan_change_later(user_id: str, draft: dict[str, Any], *, undone: bool = False) -> None:
    """确认或撤销按操作改的计划后，在后台记进管家的调整经历（spec [2026-10-23] §45）。"""
    from ironm_agent.coach_state import record_plan_later

    if draft.get("kind") != "plan" or not draft.get("ops"):
        return
    try:
        record_plan_later(coach_deps().store, user_id, draft, undone=undone)
    except Exception as e:  # 不影响这次请求
        _log.warning("plan change schedule failed: error_type=%s", type(e).__name__)


async def decided_targets(user_id: str) -> dict[str, Any]:
    """管家练完后定的下次目标（§132）；读不到当作没有，照规则。"""
    try:
        state = await coach_deps().store.get(user_id)
    except Exception as e:
        _log.info("coach state unavailable: error_type=%s", type(e).__name__)
        return {}
    return state.decided() if state is not None else {}


def targets_later(user_id: str, log: Any) -> None:
    """记下一次训练后在后台叫醒管家定下次怎么练（§132）；不耽误这次请求。"""
    from ironm_agent.next_targets import later

    try:
        later(user_id, coach_deps(), log)
    except Exception as e:
        _log.warning("next targets schedule failed: error_type=%s", type(e).__name__)


def body_later(user_id: str, text: str, day: date, where: str) -> None:
    """他在打卡备注、训练中说的话由管家读一遍：说了疼、病、累就记下，再叫醒管家（§163 规则不要）。
    在后台跑，不耽误这次请求；没说身体的事或模型失败就什么都不写。"""
    import asyncio

    from ironm_agent.body_state import read_text
    from ironm_agent.coach_state import _BACKGROUND
    from ironm_agent.llm import TurnLLM, load_models

    if not str(text or "").strip():
        return

    async def go() -> None:
        try:
            got = await read_text(user_id, text, day, where, coach_deps(), TurnLLM(load_models(), os.environ))
            if got is not None and (got.pain or got.illness or got.day):
                coach_later(user_id, f"{where}说了身体的事")
        except Exception as e:
            _log.warning("body note read failed: error_type=%s", type(e).__name__)

    task = asyncio.create_task(go())
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)


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
    decision: Literal["accept", "later", "undo"]  # undo：自动调整"不用这样调"（§84）


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
    from ironm_agent.review import daily_later

    daily_later(user_id, deps)  # 每天第一次打开对话：后台跑一次管家复盘（§85，今天做过就不再跑）
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

    deps = coach_deps()
    if body.decision == "undo":  # 管家复盘的调整"不用这样调"（§85）：计划、热量、今天都恢复原来的
        from ironm_agent.review import undo

        done = await undo(user_id, deps, body.key)
        if done is None:
            raise HTTPException(404, "这条调整已经不需要处理了")
        return {"key": body.key, "decision": "undo", "item": done.model_dump(mode="json")}
    item = await decide(deps.store, user_id, body.key, body.decision)
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
    user_id: str = Depends(_verify()),
    training: TrainingStore = TRAINING,
    illness: Any = ILLNESS,
    day: Any = DAY,
) -> dict[str, Any]:
    """本周一到周日：每天练什么、练过没有、天气和对训练的影响、按天气改出的版本（原计划不变）；
    今天生病时按症状改（spec [2026-10-23] §46）。"""
    from ironm_agent.illness import today_mode
    from ironm_agent.weather_plan import week_plan, weekday

    today = date.today()
    monday = today - timedelta(days=today.isoweekday() - 1)
    stored = await training.plan(user_id)
    rows = await training.workouts(user_id, today - timedelta(days=14))
    done = {x.log.day for x in rows if x.log.done and x.log.day >= monday}
    mode = today_mode(await _episodes(illness, user_id, today), today,
                      trained_since=[x.log.day for x in rows if x.log.done])  # fmt: skip
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
    edits = await today_edits(day, user_id, today)
    plan = with_today(stored.plan, edits, today) if stored else None  # 今天改过的按改过的（§106）
    first = stored.plan.session_on(today) if stored else None
    edits = apply_today(first, edits)[1] if first is not None else []  # 只列还套得上的
    days = week_plan(plan, wx.days if wx else (), today, now)
    weight = await _weight_now(user_id) if plan is not None else None

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
        "sick": {"mode": mode[0], "why": mode[1]} if mode else None,
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
                "edited": [e.line for e in edits] if p.day == today else [],
                **_extras(p.version or p.session, weight),
            }
            for p in days
        ],
    }


async def _weight_now(user_id: str) -> float | None:
    """最近一次体重（估算消耗用，§116）；读不到当作没有。"""
    try:
        snap = await _web().snapshot_for(user_id)
    except Exception as e:
        _log.warning("weight unavailable: error_type=%s", type(e).__name__)
        return None
    return max(snap.readings.weight)[1] if snap.readings.weight else None


def _extras(session: Any, weight: float | None) -> dict[str, Any]:
    """训练日的热身和估算消耗（§116）；休息日没有。"""
    from ironm_agent.warmup import burn, warmup

    if session is None:
        return {"warmup": None, "burn": None}
    w, b = warmup(session), burn(session.minutes, weight)
    return {
        "warmup": {"minutes": w.minutes, "steps": list(w.steps), "basis": w.basis},
        "burn": {"low": b.low, "high": b.high, "how": b.how} if b else None,
    }


async def today_edits(day: Any, user_id: str, today: date) -> list[Any]:
    """计划页"只改今天"的改动（§106）；读不到当作没改。"""
    try:
        state = await day.get(user_id, today)
    except Exception as e:
        _log.warning("day state unavailable: error_type=%s", type(e).__name__)
        return []
    return list(state.edits) if state is not None else []
