"""模型调用：按环节配置模型，超时、重试、每轮次数上限；只记录调用的元数据，不记内容。"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import Field

from ironm_agent.common import ContractModel
from ironm_agent.yamlfile import load_yaml

type Stage = Literal["route", "expert", "compose", "memory", "coach"]
# 配置里没写这个环节时沿用哪个（§142：管家的后台决策默认和作答同一个模型，旧配置不用改）
FALLBACK: dict[Stage, Stage] = {"coach": "expert"}

MODELS_PATH = Path(__file__).resolve().parent.parent / "config" / "models.yaml"


class StageModel(ContractModel):
    base_url: str
    model: str
    api_key_env: str
    extra_body: dict[str, Any] = Field(default_factory=dict)
    timeout_s: float = 30
    max_retries: int = Field(default=1, ge=0, le=3)


class ModelsConfig(ContractModel):
    turn_budget: int = Field(ge=1)
    stages: dict[Stage, StageModel]

    def route(self, stage: Stage) -> StageModel:
        """这个环节用的模型；没配时按 FALLBACK 沿用别的环节。"""
        if stage in self.stages:
            return self.stages[stage]
        return self.stages[FALLBACK[stage]]


def load_models(path: Path = MODELS_PATH) -> ModelsConfig:
    return ModelsConfig.model_validate(load_yaml(path), strict=False)


class ModelUnavailable(Exception):
    """模型这次不能用：没有密钥、超时、出错，或者这一轮的次数用完了。"""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Reply:
    content: str
    tool_calls: tuple[ToolCall, ...] = ()

    def as_message(self) -> dict[str, Any]:
        """作为助手消息放回对话（有工具调用时带上调用）。"""
        msg: dict[str, Any] = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {
                        "name": c.name,
                        "arguments": json.dumps(c.arguments, ensure_ascii=False),
                    },
                }
                for c in self.tool_calls
            ]
        return msg


@dataclass(frozen=True)
class CallRecord:
    stage: Stage
    model: str
    ms: int
    ok: bool
    error_type: str | None = None
    prompt: int = 0  # 输入多少 token（§165）
    cached: int = 0  # 其中命中提示缓存的（DeepSeek 的 prompt_cache_hit_tokens）


class LLM(Protocol):
    calls: list[CallRecord]

    async def chat(
        self,
        stage: Stage,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
        json_mode: bool = False,
    ) -> Reply: ...


@dataclass
class TurnLLM:
    """一轮对话用的模型客户端：次数上限按轮计算。"""

    config: ModelsConfig
    environ: Mapping[str, str]
    calls: list[CallRecord] = field(default_factory=list)

    async def chat(
        self,
        stage: Stage,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
        json_mode: bool = False,
    ) -> Reply:
        route = self.config.route(stage)
        key = self.environ.get(route.api_key_env, "")
        if not key:
            raise ModelUnavailable("missing_key")
        last: Exception | None = None
        for _ in range(route.max_retries + 1):
            if len(self.calls) >= self.config.turn_budget:
                raise ModelUnavailable("budget")
            start = time.perf_counter()
            try:
                reply, usage = await _request(route, key, messages, tools, json_mode)
            except Exception as e:  # 超时、网络、服务端出错：重试一次
                self.calls.append(_record(stage, route, start, e))
                last = e
                continue
            self.calls.append(_record(stage, route, start, None, usage))
            return reply
        raise ModelUnavailable(type(last).__name__ if last else "unknown")


def _record(
    stage: Stage, route: StageModel, start: float, error: Exception | None, usage: tuple[int, int] = (0, 0)
) -> CallRecord:
    ms = int((time.perf_counter() - start) * 1000)
    return CallRecord(
        stage, route.model, ms, error is None, type(error).__name__ if error else None, *usage
    )


async def _request(
    route: StageModel,
    key: str,
    messages: Sequence[Mapping[str, Any]],
    tools: Sequence[Mapping[str, Any]] | None,
    json_mode: bool,
) -> tuple[Reply, tuple[int, int]]:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=key, base_url=route.base_url, timeout=route.timeout_s, max_retries=0
    )
    kwargs: dict[str, Any] = {"model": route.model, "messages": list(messages), "temperature": 0.3}
    if tools:
        kwargs["tools"] = list(tools)
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if route.extra_body:
        kwargs["extra_body"] = route.extra_body
    try:
        resp = await client.chat.completions.create(**kwargs)
    finally:
        await client.close()
    msg = resp.choices[0].message
    calls = tuple(
        ToolCall(c.id, c.function.name, _arguments(c.function.arguments))
        for c in (msg.tool_calls or [])
        if c.type == "function"
    )
    u = resp.usage
    usage = (int(getattr(u, "prompt_tokens", 0) or 0), int(getattr(u, "prompt_cache_hit_tokens", 0) or 0)) if u else (0, 0)
    return Reply(msg.content or "", calls), usage


def _arguments(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def parse_json(text: str) -> dict[str, Any] | None:
    """从模型输出里取出 JSON 对象；外面包了代码块也能取。取不出时返回 None。"""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None
