"""测试用的假模型与假健康数据：不调用任何真实服务。"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ironm_agent.llm import CallRecord, ModelUnavailable, Reply, Stage, ToolCall

type Handler = Callable[[Stage, Sequence[Mapping[str, Any]], bool], Reply]


@dataclass
class FakeLLM:
    """按环节返回预设的回答；handler 拿到环节、消息和是否提供了工具。"""

    handler: Handler
    calls: list[CallRecord] = field(default_factory=list)
    seen: list[tuple[Stage, list[Mapping[str, Any]]]] = field(default_factory=list)

    async def chat(
        self,
        stage: Stage,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
        json_mode: bool = False,
    ) -> Reply:
        self.calls.append(CallRecord(stage, "fake", 0, True))
        self.seen.append((stage, list(messages)))
        return self.handler(stage, messages, bool(tools))


def down(*_: Any) -> Reply:
    raise ModelUnavailable("missing_key")


def jsonr(data: Mapping[str, Any]) -> Reply:
    return Reply(json.dumps(data, ensure_ascii=False))


def route_reply(
    intent: str = "pro", primary: str | None = None, helpers: Sequence[str] = ()
) -> Reply:
    """路由模型这一路的回答（spec [2026-10-23] §16）：主责 1.0、辅助 0.9，其余 0。"""
    scores = {r: 0.0 for r in ("planner", "exercise", "nutrition", "recovery", "data")}
    if primary:
        scores[primary] = 1.0
    for h in helpers:
        scores[h] = 0.9
    return jsonr({"intent": intent, "scores": scores})


def call(name: str, **args: Any) -> Reply:
    return Reply("", (ToolCall(f"c-{name}", name, dict(args)),))


def system_of(messages: Sequence[Mapping[str, Any]]) -> str:
    return str(messages[0]["content"]) if messages else ""


def tool_results(messages: Sequence[Mapping[str, Any]]) -> list[str]:
    return [str(m["content"]) for m in messages if m.get("role") == "tool"]


ROWS = [
    {
        "name": "restingHeartRates",
        "count": 30,
        "min": 54,
        "max": 63,
        "avg": 58.2,
        "unit": "/min",
        "rid": "r1",
    },
]


@dataclass
class FakeHealth:
    """假的 mirobody 健康数据查询：返回真实的信封类型，渲染走 mirobody 自己的代码。"""

    rows: list[dict[str, Any]] = field(default_factory=lambda: list(ROWS))
    fail: bool = False
    asked: list[dict[str, Any]] = field(default_factory=list)

    async def envelope(self, user_info: Mapping[str, Any], **args: Any) -> Any:
        from mirobody.kernel.tools import Envelope

        self.asked.append({"user_info": dict(user_info), **args})
        if self.fail:
            raise ConnectionError("db down")
        return Envelope("ok", data=self.rows)
