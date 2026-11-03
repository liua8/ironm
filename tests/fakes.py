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


def call(name: str, **args: Any) -> Reply:
    return Reply("", (ToolCall(f"c-{name}", name, dict(args)),))


def again(result: str) -> bool:
    """被退回了、值得照原样再交一次：没出预览，也不是让（或已在）先确认条件。"""
    return not result.startswith("已出") and "排新计划" not in result


def remembering(
    memory: Sequence[Mapping[str, Any]], answer: Mapping[str, Any], *before: Reply
) -> Callable[..., Reply]:
    """单 Agent 的假模型（§145）：先依次交 before 里的调用，再调 remember 交这些记忆，最后作答。"""
    steps = [*before, call("remember", items=[dict(x) for x in memory])]

    def reply(*args: Any) -> Reply:
        results = args[-1] if args and isinstance(args[-1], list) else []
        return steps[len(results)] if len(results) < len(steps) else jsonr(answer)

    return reply


def acting(
    name: str, args: Mapping[str, Any], answer: Mapping[str, Any], tries: int = 2
) -> Callable[[str, str, list[str]], Reply]:
    """单 Agent 的假模型（§120）：先调用动作工具；被退回就照原样再交（最多 tries 次），出了预览或交够了再作答。"""

    def reply(system: str, user: str, results: list[str]) -> Reply:
        if not results or (len(results) < tries and again(results[-1])):
            return call(name, **args)
        return jsonr(answer)

    return reply


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
