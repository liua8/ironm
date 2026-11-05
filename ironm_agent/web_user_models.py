"""用自己的模型的接口（spec [2026-11-03] §153）：看、存、删、测试。密钥只进不出（只给末四位），日志不记。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ironm_agent.user_models import PRESETS, BadAddress, ModelStore, Provider, UserModel, check_url
from ironm_agent.user_models import default_models as model_store
from ironm_agent.user_models import test_connection as _test
from ironm_agent.web_more import _verify

_log = logging.getLogger(__name__)
router = APIRouter()
MODELS = Depends(model_store)  # 测试时换成内存版


class ModelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Provider
    base_url: str = Field(default="", max_length=200)
    api_key: str = Field(default="", max_length=300)  # 改别的不改密钥时留空，沿用存着的
    chat_model: str = Field(min_length=1, max_length=80)
    vision_model: str = Field(default="", max_length=80)


async def _build(body: ModelIn, user_id: str, store: ModelStore) -> UserModel:
    key = body.api_key.strip()
    if not key:
        old = await store.get(user_id)
        if old is None:
            raise HTTPException(422, "填一下 API 密钥")
        key = old.api_key
    try:
        url = check_url(body.provider, body.base_url)
    except BadAddress as e:
        raise HTTPException(422, str(e)) from e
    if len(key) < 8:
        raise HTTPException(422, "API 密钥看着不完整")
    return UserModel(provider=body.provider, base_url=url, api_key=key,
                     chat_model=body.chat_model.strip(), vision_model=body.vision_model.strip())  # fmt: skip


@router.get("/iron/api/my-model")
async def get_my_model(
    user_id: str = Depends(_verify()), store: ModelStore = MODELS
) -> dict[str, Any]:
    m = await store.get(user_id)
    presets = {k: {"name": p.name, "base_url": p.base_url, "chat": list(p.chat), "vision": list(p.vision)}
               for k, p in PRESETS.items()}  # fmt: skip
    return {"model": m.public() if m else None, "presets": presets}


@router.put("/iron/api/my-model")
async def put_my_model(
    body: ModelIn, user_id: str = Depends(_verify()), store: ModelStore = MODELS
) -> dict[str, Any]:
    m = await _build(body, user_id, store)
    await store.put(user_id, m)
    _log.info("user model saved: provider=%s", m.provider)
    return {"model": m.public()}


@router.delete("/iron/api/my-model")
async def delete_my_model(
    user_id: str = Depends(_verify()), store: ModelStore = MODELS
) -> dict[str, Any]:
    await store.drop(user_id)
    _log.info("user model removed")
    return {"model": None}


@router.post("/iron/api/my-model/test")
async def test_my_model(
    body: ModelIn, user_id: str = Depends(_verify()), store: ModelStore = MODELS
) -> dict[str, Any]:
    """用填的（或存着的）密钥试一次：通不通、能不能调工具、能不能看图。"""
    return await _test(await _build(body, user_id, store))


def mail_ready() -> bool:
    """发信服务配好了没有（和底座选发信方式的条件一样：SMTP 的地址、账号、密码都有）。"""
    try:
        from mirobody.utils.config.config import global_config

        cfg = global_config()
        opts = cfg.get_email_options() if cfg is not None else {}
    except Exception as e:
        _log.warning("mail options unavailable: error_type=%s", type(e).__name__)
        return False
    return all(opts.get(k) for k in ("email_smtp_host", "email_smtp_user", "email_password"))


@router.get("/iron/api/auth/options")
async def auth_options() -> dict[str, Any]:
    """登录页用：能不能注册、能不能找回密码（要发得出验证码，§155）。不用登录。"""
    return {"mail": mail_ready()}
