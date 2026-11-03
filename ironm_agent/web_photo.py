"""打卡照片的接口（spec [2026-10-23] §117）：给自己的一条训练记录传一张、取这张。存法在 checkin_photo.py。

照片只按登录的人取，别人的记录编号一律 404；照片不交给模型；日志不记图片。
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile

from ironm_agent.checkin_photo import PhotoStore
from ironm_agent.meals import MAX_PHOTO_BYTES
from ironm_agent.training import TrainingStore
from ironm_agent.web import _verify, training_store
from ironm_agent.web_more import PHOTO_TYPES, PHOTOS

_log = logging.getLogger("ironm_agent.checkin_photo")
router: APIRouter = APIRouter()
TRAINING: Any = Depends(training_store)
FAR = date(2000, 1, 1)  # 查某条训练记录是不是他的：从很早算起


@router.post("/iron/api/workouts/{workout_id}/photo")
async def add_checkin_photo(
    workout_id: str,
    photo: Annotated[UploadFile | None, File()] = None,
    user_id: str = Depends(_verify()),
    store: PhotoStore = PHOTOS,
    training: TrainingStore = TRAINING,
) -> dict[str, Any]:
    """打卡随手拍的一张，挂在这条训练记录上；再传一张就换掉。"""
    if not any(x.id == workout_id for x in await training.workouts(user_id, FAR)):
        raise HTTPException(404, "这条训练记录不存在")
    if photo is None or not photo.filename:
        raise HTTPException(422, "选一张照片")
    mime = photo.content_type or ""
    if mime not in PHOTO_TYPES:
        raise HTTPException(415, "照片只支持 JPG、PNG、WebP")
    data = await photo.read(MAX_PHOTO_BYTES + 1)
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "照片不能超过 5MB")
    await store.put(user_id, workout_id, data, mime)
    _log.info("checkin photo added")
    return {"workout_id": workout_id, "photo": True}


@router.get("/iron/api/workouts/{workout_id}/photo")
async def get_checkin_photo(
    workout_id: str, user_id: str = Depends(_verify()), store: PhotoStore = PHOTOS
) -> Response:
    found = await store.get(user_id, workout_id)
    if found is None:
        raise HTTPException(404, "没有这张照片")
    return Response(
        found[0], media_type=found[1], headers={"Cache-Control": "private, max-age=600"}
    )
