"""专业 Agent 能用的工具：查这个人在 mirobody 里的健康数据、查本领域的依据库。

每个 Agent 只能用自己角色允许的工具；查到的数据行与资料条目都记下来，作为核对数字与引用的依据。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ironm_agent.kb import Entry, KnowledgeBase
from ironm_agent.llm import ToolCall
from ironm_agent.roles import RoleSpec

_log = logging.getLogger("ironm_agent.tools")

HEALTH = "query_health_indicators"
KNOWLEDGE = "search_knowledge"
METRICS = "compute_metrics"

# 能调用指标计算的角色（BMI、基础代谢、热量与蛋白质目标、体重趋势、与本人基线的比较）
METRIC_ROLES = frozenset({"data", "nutrition", "recovery", "planner"})

METRICS_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": METRICS,
        "description": (
            "计算这个人的指标：体重与每周变化、BMI、基础代谢、每日总消耗、每日热量与蛋白质目标、"
            "静息心率与心率变异性和本人基线的比较、睡眠、步数、血压。每项带编号（如 C2）、计算过程、所用数据和依据；"
            "缺数据的项会写明还缺什么。与 App 数据页是同一份计算。"
        ),
        "parameters": {"type": "object", "additionalProperties": False, "properties": {}},
    },
}

type MetricsSource = Callable[[], Awaitable[list[Any]]]


def _health_schema() -> dict[str, Any]:
    from mirobody.kernel.query import TOOL_SCHEMA

    return {
        "type": "function",
        "function": {
            "name": HEALTH,
            "description": (
                "查询这个人在健康记录里的数据（体重、静息心率、心率变异性、睡眠、步数、血压、化验等）。"
                "不知道指标名时先不带 keywords/indicators 调用，拿到这个人有哪些数据的目录；"
                "问变化、平均、基线用 view=stats，问趋势用 view=day 或 week，问现在多少用 view=latest。"
                "返回的每行有 rid（如 r3），引用这行数据时用它。没有返回某个指标，说明没有记录，不代表正常。"
            ),
            "parameters": TOOL_SCHEMA,
        },
    }


KNOWLEDGE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": KNOWLEDGE,
        "description": "在本领域的依据库里查资料（指南、立场声明、系统综述等），返回带编号（如 K03）的条目。",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"query": {"type": "string", "description": "要查的内容，用中文关键词"}},
            "required": ["query"],
        },
    },
}


@dataclass
class Evidence:
    """一个 Agent 这一轮查到的全部依据。"""

    support: dict[str, list[float]] = field(default_factory=dict)  # 健康数据行 rid → 这行的数值
    entries: dict[str, Entry] = field(default_factory=dict)  # 查到的依据库条目
    calcs: dict[str, str] = field(default_factory=dict)  # 指标计算结果 C 编号 → 说明（含数字）
    rows: dict[str, str] = field(default_factory=dict)  # 健康数据行 rid → 给人看的一句说明
    health_queries: int = 0
    knowledge_queries: int = 0
    metric_queries: int = 0
    health_failed: bool = False

    @property
    def queries(self) -> int:
        return self.health_queries + self.knowledge_queries + self.metric_queries


def row_numbers(row: Mapping[str, Any]) -> list[float]:
    from mirobody.kernel.citations import numbers

    out: list[float] = []
    for key, value in row.items():
        if key in ("rid", "name", "display", "code", "system", "source", "file"):
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            out.append(float(value))
        elif isinstance(value, str):
            out.extend(numbers(value))
    return out


_VALUE_FIELDS = (
    ("value", "值"),
    ("avg", "平均"),
    ("min", "最低"),
    ("max", "最高"),
    ("last", "最近"),
)


def row_label(row: Mapping[str, Any]) -> str:
    """一行健康数据给人看的说明：指标、时间、主要数值。"""
    name = row.get("indicator") or row.get("name") or "数据"
    when = str(row.get("period") or row.get("date") or "")
    if not when and (row.get("first_date") or row.get("last_date")):
        when = f"{row.get('first_date') or ''} 至 {row.get('last_date') or ''}"
    unit = str(row.get("unit") or "")
    parts = [
        f"{label} {row[k]}{(' ' + unit) if unit and k != 'last' else ''}"
        for k, label in _VALUE_FIELDS
        if row.get(k) not in (None, "")
    ]
    count = row.get("count") or row.get("n")
    if count:
        parts.append(f"共 {count} 条")
    return f"{name}（{when}）：" + "，".join(parts) if when else f"{name}：" + "，".join(parts)


def _default_render(envelope: Any) -> str:
    from mirobody.agent.tools._render import render_compact

    return str(render_compact(envelope))


class Toolbox:
    """一个 Agent 在一轮里的工具箱。"""

    def __init__(
        self,
        spec: RoleSpec,
        *,
        kb: KnowledgeBase,
        health: Any | None,
        user_id: str,
        session_id: str,
        render: Callable[[Any], str] = _default_render,
        metrics: MetricsSource | None = None,
    ) -> None:
        self.spec = spec
        self.kb = kb
        self.health = health if spec.health_data else None
        self.metrics = metrics if spec.role.value in METRIC_ROLES else None
        self.user_info = {"user_id": user_id, "session_id": session_id}
        self.render = render
        self.evidence = Evidence()

    def schemas(self) -> list[dict[str, Any]]:
        out = [KNOWLEDGE_SCHEMA] if self.spec.kb_domains else []
        if self.health is not None:
            out.append(_health_schema())
        if self.metrics is not None:
            out.append(METRICS_SCHEMA)
        return out

    async def run(self, call: ToolCall) -> str:
        if call.name == KNOWLEDGE and self.spec.kb_domains:
            return self._knowledge(str(call.arguments.get("query", "")))
        if call.name == HEALTH and self.health is not None:
            return await self._health(call.arguments)
        if call.name == METRICS and self.metrics is not None:
            return await self._metrics()
        return json.dumps({"error": f"{self.spec.name}不能使用这个工具"}, ensure_ascii=False)

    async def _metrics(self) -> str:
        self.evidence.metric_queries += 1
        try:
            items = await self.metrics()  # type: ignore[misc]
        except Exception as e:
            _log.warning("metrics failed: error_type=%s", type(e).__name__)
            return "这次没能计算指标。"
        lines = []
        for i, m in enumerate(items, start=1):
            if m.value is None:
                lines.append(f"- {m.name}：算不出来，{m.text}")
                continue
            cid = f"C{i}"
            detail = f"{m.name}：{m.text}。计算：{m.how}。数据：{m.data}。依据：{m.source}"
            self.evidence.calcs[cid] = detail
            lines.append(f"[{cid}] {detail}")
        return "\n".join(lines) or "没有可计算的指标。"

    def _knowledge(self, query: str) -> str:
        self.evidence.knowledge_queries += 1
        found = self.kb.search(query, self.spec.kb_domains)
        for e in found:
            self.evidence.entries[e.id] = e
        if not found:
            return "依据库里没有找到相关资料。"
        return "\n\n".join(e.as_evidence() for e in found)

    async def _health(self, args: Mapping[str, Any]) -> str:
        self.evidence.health_queries += 1
        try:
            envelope = await self.health.envelope(self.user_info, **dict(args))  # type: ignore[union-attr]
        except Exception as e:  # 读不到数据不影响作答：如实告诉模型
            _log.warning("health query failed: error_type=%s", type(e).__name__)
            self.evidence.health_failed = True
            return "这次没能读取健康数据。"
        if getattr(envelope, "status", "ok") == "error":
            self.evidence.health_failed = True
            kind = getattr(envelope, "error_kind", None) or "error"
            return f"查询没有成功（{kind}），可以换个参数再试，或者如实说明没读到数据。"
        for row in getattr(envelope, "data", None) or []:
            rid = row.get("rid") if isinstance(row, Mapping) else None
            if isinstance(rid, str) and rid:
                self.evidence.support[rid] = row_numbers(row)
                self.evidence.rows[rid] = row_label(row)
        return self.render(envelope)
