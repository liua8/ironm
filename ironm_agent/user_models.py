"""用自己的模型（spec [2026-11-03] §153、[2026-11-05] §167）：每个人填自己的 API，没有默认模型。

- 服务商预设（PRESETS）或自定义（兼容 OpenAI 格式）；自定义地址只许 https 公网地址（防止被拿来访问内网）。
- 密钥用 mirobody 的加密函数存；对外只给末四位；日志不记密钥和接口返回的内容。
- pick(user_id)：他自己填的模型（所有环节都走他的对话模型，看图走看图模型）；没填返回 None，
  调用方说"先填你自己的模型"（网页接口回 428），后台任务跳过。不拿服务器的密钥顶上。
  他的模型出错时如实说，调用方提示他去"模型和 API"里测试。
"""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import logging
import socket
import struct
import zlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from ironm_agent.ddl import run_ddl
from ironm_agent.llm import LLM, ModelsConfig, Reply, StageModel, TurnLLM, _request, load_models

_log = logging.getLogger(__name__)
KEY_ENV = "IRONM_USER_API_KEY"  # 他的密钥只放在这一轮的 environ 里，不进进程的环境变量


@dataclass(frozen=True)
class Preset:
    name: str
    base_url: str
    chat: tuple[str, ...] = ()  # 常用的对话模型（也能自己填）
    vision: tuple[str, ...] = ()  # 常用的看图模型
    extra_body: Mapping[str, Any] | None = None


PRESETS: dict[str, Preset] = {
    "deepseek": Preset("DeepSeek", "https://api.deepseek.com", ("deepseek-flash", "deepseek-v4-pro"),
                       ("deepseek-flash",), {"thinking": {"type": "disabled"}}),
    "zhipu": Preset("智谱", "https://open.bigmodel.cn/api/paas/v4", (), ("glm-4.6v-flash", "glm-4.6v")),
    "qwen": Preset("通义千问（阿里云百炼）", "https://dashscope.aliyuncs.com/compatible-mode/v1",
                   ("qwen-plus", "qwen-max", "qwen-turbo"), ("qwen-vl-plus", "qwen-vl-max")),
    "doubao": Preset("豆包（火山方舟）", "https://ark.cn-beijing.volces.com/api/v3"),
    "kimi": Preset("Kimi（月之暗面）", "https://api.moonshot.cn/v1"),
    "openai": Preset("OpenAI", "https://api.openai.com/v1"),
}  # fmt: skip
Provider = Literal["deepseek", "zhipu", "qwen", "doubao", "kimi", "openai", "custom"]


class UserModel(BaseModel):
    provider: Provider
    base_url: str = Field(max_length=200)
    api_key: str = Field(min_length=8, max_length=300)
    chat_model: str = Field(min_length=1, max_length=80)
    vision_model: str = Field(default="", max_length=80)
    updated: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def public(self) -> dict[str, Any]:
        """给页面看的：密钥只给末四位。"""
        return {
            "provider": self.provider, "base_url": self.base_url, "key_tail": self.api_key[-4:],
            "chat_model": self.chat_model, "vision_model": self.vision_model,
            "updated": self.updated.isoformat(),
        }  # fmt: skip


class BadAddress(ValueError):
    pass


def check_url(provider: str, base_url: str) -> str:
    """预设用预设的地址；自定义的只许 https、主机解析出来全是公网地址。返回要用的地址。"""
    if provider in PRESETS:
        return PRESETS[provider].base_url
    u = urlparse(base_url.strip())
    if u.scheme != "https" or not u.hostname:
        raise BadAddress("接口地址要以 https:// 开头")
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or 443, proto=socket.IPPROTO_TCP)
    except OSError as e:
        raise BadAddress("这个地址解析不出来，检查一下有没有写错") from e
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise BadAddress("不能用内网或本机的地址")
    return base_url.strip().rstrip("/")


def config_for(m: UserModel) -> ModelsConfig:
    """他的模型配置：所有对话环节都用他的对话模型，看图用看图模型（没填用对话模型）。"""
    extra = dict(PRESETS[m.provider].extra_body or {}) if m.provider in PRESETS else {}

    def stage(model: str) -> StageModel:
        return StageModel(base_url=m.base_url, model=model, api_key_env=KEY_ENV,
                          extra_body=extra, timeout_s=45, max_retries=1)  # fmt: skip

    chat = stage(m.chat_model)
    return ModelsConfig(
        turn_budget=load_models().turn_budget,
        stages={"route": chat, "expert": chat, "compose": chat, "memory": chat, "coach": chat,
                "vision": stage(m.vision_model or m.chat_model)},
    )  # fmt: skip


# ---- 存储 -------------------------------------------------------------------------------------


class ModelStore(Protocol):
    async def get(self, user_id: str) -> UserModel | None: ...
    async def put(self, user_id: str, m: UserModel) -> None: ...
    async def drop(self, user_id: str) -> None: ...


class ModelBook:
    """内存版（测试用）。"""

    def __init__(self) -> None:
        self.rows: dict[str, UserModel] = {}

    async def get(self, user_id: str) -> UserModel | None:
        return self.rows.get(user_id)

    async def put(self, user_id: str, m: UserModel) -> None:
        self.rows[user_id] = m

    async def drop(self, user_id: str) -> None:
        self.rows.pop(user_id, None)


DDL = (
    """
CREATE TABLE IF NOT EXISTS ironm_user_model (
    user_id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)""",
)


class PgModels:
    """数据库版：整条（含密钥）用 mirobody 的加密函数加密。"""

    def __init__(self) -> None:
        self._ready = False

    async def _q(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        from mirobody.utils.db import execute_query

        if not self._ready:
            await run_ddl(*DDL)
            self._ready = True
        rows = await execute_query(sql, params, log_sql=False)
        return rows if isinstance(rows, list) else []

    async def get(self, user_id: str) -> UserModel | None:
        rows = await self._q(
            "SELECT decrypt_content(content) AS content FROM ironm_user_model WHERE user_id = :uid",
            {"uid": user_id},
        )
        return UserModel.model_validate_json(rows[0]["content"]) if rows else None

    async def put(self, user_id: str, m: UserModel) -> None:
        await self._q(
            "INSERT INTO ironm_user_model (user_id, content) VALUES (:uid, encrypt_content(:c))"
            " ON CONFLICT (user_id) DO UPDATE SET content = EXCLUDED.content, updated_at = now()",
            {"uid": user_id, "c": m.model_dump_json()},
        )

    async def drop(self, user_id: str) -> None:
        await self._q("DELETE FROM ironm_user_model WHERE user_id = :uid", {"uid": user_id})


_store: ModelStore | None = None


def default_models() -> ModelStore:
    global _store
    if _store is None:
        _store = PgModels()
    return _store


OWN_FAILED = "你填的模型这次没调通，去「我 → 模型和 API」里测试一下。"
NO_MODEL = "先在「我 → 模型和 API」填你自己的模型，这个功能要用你的模型。"


async def own_config(
    user_id: str, store: ModelStore | None = None
) -> tuple[ModelsConfig, dict[str, str]] | None:
    """这个人自己填的模型的配置和密钥（对话链路自己建模型时用，§167）；没填返回 None，读不到设置时抛出。"""
    m = await (store or default_models()).get(user_id)
    return None if m is None else (config_for(m), {KEY_ENV: m.api_key})


async def pick(user_id: str, store: ModelStore | None = None) -> LLM | None:
    """这个人自己填的模型；没填返回 None（§167：没有默认模型，不拿服务器的密钥顶上）。
    读不到设置时照样抛出，由调用方说"稍后再试"，不当成没填。"""
    got = await own_config(user_id, store)
    return None if got is None else TurnLLM(*got)


async def pick_quiet(user_id: str) -> LLM | None:
    """后台任务用：没填或读不到设置都返回 None，这一步就不做（§167 需求 3），只记错误类型。"""
    try:
        return await pick(user_id)
    except Exception as e:
        _log.warning("user model unavailable: error_type=%s", type(e).__name__)
        return None


# ---- 测试连接 ---------------------------------------------------------------------------------

_PING_TOOL = {
    "type": "function",
    "function": {
        "name": "ping",
        "description": "测试用：收到就调用一次",
        "parameters": {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        },
    },
}


def _red_png(size: int = 64) -> bytes:
    """一张纯红的小图（看图测试用），不依赖图片库。"""
    row = b"\x00" + b"\xff\x00\x00" * size
    raw = zlib.compress(row * size)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    head = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


def _why(e: Exception) -> str:
    """出错原因说人话；不带密钥和接口返回的原文。"""
    code = getattr(getattr(e, "response", None), "status_code", None) or getattr(
        e, "status_code", None
    )
    if code in (401, 403):
        return "密钥不对或没有权限"
    if code == 402:
        return "账户余额不足"
    if code == 404:
        return "没有这个模型，或接口地址不对"
    if code == 429:
        return "请求太频繁或额度用完了"
    if isinstance(code, int) and code >= 500:
        return "服务商那边暂时出错，稍后再试"
    if isinstance(e, asyncio.TimeoutError | TimeoutError) or "Timeout" in type(e).__name__:
        return "连接超时"
    if "Connection" in type(e).__name__:
        return "连不上这个地址"
    return f"没调通（{type(e).__name__}{f'，{code}' if code else ''}）"


async def _try(route: StageModel, key: str, messages: Any, tools: Any) -> Reply:
    """测试用的一次请求：服务商那边出错（5xx）或超时时再试一次。只要回复，不要用量（§165 起请求带回用量）。"""
    try:
        return (await _request(route, key, messages, tools, False))[0]
    except Exception as e:
        code = getattr(e, "status_code", None)
        if not ((isinstance(code, int) and code >= 500) or "Timeout" in type(e).__name__):
            raise
    return (await _request(route, key, messages, tools, False))[0]


async def test_connection(m: UserModel) -> dict[str, Any]:
    """通不通、能不能调工具、能不能看图，分开报。用他的密钥，只发很短的内容。"""
    cfg = config_for(m)
    out: dict[str, Any] = {}
    chat = cfg.route("expert")
    try:
        await _try(chat, m.api_key, [{"role": "user", "content": "回复 ok"}], None)
        out["chat"] = {"ok": True}
    except Exception as e:
        out["chat"] = {"ok": False, "why": _why(e)}
        return out | {
            "tools": {"ok": False, "why": "没通，没试"},
            "vision": {"ok": False, "why": "没通，没试"},
        }
    try:
        r = await _try(
            chat,
            m.api_key,
            [{"role": "user", "content": "调用 ping 工具，ok 填 true"}],
            [_PING_TOOL],
        )
        out["tools"] = {"ok": bool(r.tool_calls)} | (
            {} if r.tool_calls else {"why": "这个模型没有调用工具，IronM 对话用不了"}
        )
    except Exception as e:
        out["tools"] = {"ok": False, "why": _why(e)}
    url = "data:image/png;base64," + base64.b64encode(_red_png()).decode()
    try:
        r = await _try(cfg.route("vision"), m.api_key, [{"role": "user", "content": [
            {"type": "text", "text": "这张图是什么颜色？只答颜色。"},
            {"type": "image_url", "image_url": {"url": url}}]}], None)  # fmt: skip
        seen = "红" in r.content or "red" in r.content.lower()
        out["vision"] = {"ok": seen} | ({} if seen else {"why": "这个模型好像看不了图"})
    except Exception as e:
        out["vision"] = {"ok": False, "why": _why(e)}
    _log.info("user model test: %s", {k: v["ok"] for k, v in out.items()})
    return out
