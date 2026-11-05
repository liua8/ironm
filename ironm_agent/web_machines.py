"""认器械的接口（spec [2026-11-03] §149）：器械清单（带配图和能练的动作）、拍照识别。照片不保存，日志不记图片。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from ironm_agent import machines as mc
from ironm_agent.exercise_images import gif_for, images_for
from ironm_agent.exercises import library
from ironm_agent.meals import MAX_PHOTO_BYTES
from ironm_agent.user_models import OWN_FAILED
from ironm_agent.web_more import PHOTO_TYPES, _verify

_log = logging.getLogger(__name__)

router = APIRouter()
PHOTO = File(...)


def _picture(move_ids: tuple[str, ...]) -> dict[str, Any] | None:
    """卡片配图：按动作顺序找第一个有动图或图片的。"""
    for i in move_ids:
        if got := gif_for(i) or next(iter(images_for(i)), None):
            return got
    return None


@router.get("/iron/api/machines")
async def get_machines(user_id: str = Depends(_verify())) -> dict[str, Any]:
    names = {x.id: x.name for x in library().exercises}
    return {"machines": [
        {**m.model_dump(), "moves": [{"id": i, "name": names[i]} for i in m.moves], "picture": _picture(m.moves)}
        for m in mc.machines()
    ]}  # fmt: skip


@router.post("/iron/api/machines/recognize")
async def recognize_machine(
    photo: UploadFile = PHOTO, user_id: str = Depends(_verify())
) -> dict[str, Any]:
    """拍一张认器械：模型看照片直接写是什么、怎么用；没有模型时回 no_model，页面引导从清单里选。"""
    mime = photo.content_type or ""
    if mime not in PHOTO_TYPES:
        raise HTTPException(415, "照片只支持 JPG、PNG、WebP")
    data = await photo.read(MAX_PHOTO_BYTES + 1)
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "照片不能超过 5MB")
    from ironm_agent.web_more import need_llm

    llm = await need_llm(user_id)  # 用他自己填的看图模型（§167）；没填回 428
    got = await mc.recognize(data, mime, mc.looker(llm))
    if got.status == "failed":
        return {**got.json(), "message": OWN_FAILED}
    _log.info("machine recognize: status=%s", got.status)
    return got.json()
