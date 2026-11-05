"""专业 Agent 能用的工具：查这个人在 mirobody 里的健康数据、查本领域的依据库。

每个 Agent 只能用自己角色允许的工具；查到的数据行与资料条目都记下来，作为核对数字与引用的依据。
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from ironm_agent.actions import ACTION_TOOLS, Desk
from ironm_agent.kb import Entry, KnowledgeBase
from ironm_agent.llm import ToolCall
from ironm_agent.protools import registry as pro
from ironm_agent.roles import RoleSpec

_log = logging.getLogger("ironm_agent.tools")
_OUTCOME: ContextVar[str] = ContextVar("tool_outcome", default="ok")
# 页面上的进度（§165）：每开始一步告诉页面在做什么；没列的用工具清单里的名字
STEP_NAMES = {
    "search_knowledge": "查资料", "search_exercises": "查动作", "query_health_indicators": "看你的健康数据",
    "compute_metrics": "算指标", "plan_templates": "挑方案", "check_plan": "检查计划",
    "propose_new_plan": "排计划", "propose_plan_edit": "改计划", "propose_temporary_change": "排临时调整",
    "log_workout": "记训练", "recall_memory": "翻你以前说的", "estimate_strength": "估重量",
    "find_substitutes": "找替代动作", "training_patterns": "看训练记录", "pain_check": "判断疼痛",
    "nutrition_calc": "算营养", "trend_analysis": "看趋势", "explain_trends": "解读数据",
    "app_help": "查 App 用法", "search_web": "联网查", "load_skill": "翻做法", "timeline": "看时间线",
}  # fmt: skip
QUIET_STEPS = frozenset({"record_state", "remember"})  # 每轮顺手记的，不当一步给他看
type Progress = Callable[[str, str, str, bool | None], None]  # (编号, 名字, 说明, 结果：None 表示刚开始)

HEALTH = "query_health_indicators"
KNOWLEDGE = "search_knowledge"
METRICS = "compute_metrics"
EXERCISES = "search_exercises"
MEDS = "query_medications"  # mirobody 的用药记录（spec [2026-10-23] §25）
MEDICAL = "search_medical_knowledge"  # mirobody 的医学知识（部署配置了才有）

# 能查用药记录的角色：判断运动风险（降压药、胰岛素等）
MEDS_ROLES = frozenset({"recovery", "general"})
# 能查医学知识的角色：问到检验项目、药物副作用时
MEDICAL_ROLES = frozenset({"recovery", "nutrition", "general"})

type MedicalSearch = Callable[[str, str], Awaitable[str]]
type ExtraTool = Callable[["Toolbox", Mapping[str, Any]], Awaitable[str]]


def _meds_schema() -> dict[str, Any]:
    from mirobody.kernel.meds import TOOL_SCHEMA

    return {
        "type": "function",
        "function": {
            "name": MEDS,
            "description": (
                "查询这个人健康记录里的用药（药名、剂量、开始和停止时间）。判断运动风险时用："
                "如降压药（尤其β受体阻滞剂会让心率偏低）、胰岛素和降糖药（运动时防低血糖）。"
                "没有返回说明没有记录，不代表没在吃药；不建议改药、停药。"
            ),
            "parameters": TOOL_SCHEMA,
        },
    }


MEDICAL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": MEDICAL,
        "description": (
            "查通用医学知识：检验项目是什么意思、药物的作用和副作用、疾病是什么（来自 MedlinePlus、"
            "美国 FDA 药品说明书等）。不读这个人的记录。query 用英文医学词，不要写这个人的名字、数值和日期。"
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {
                    "type": "string",
                    "description": "英文医学词，如 metoprolol exercise heart rate",
                }
            },
            "required": ["query"],
        },
    },
}

# 能查动作库的角色（做法、要点、常见错误、替代、什么情况先别做）
LIBRARY_ROLES = frozenset({"trainer", "recovery", "general"})

EXERCISES_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": EXERCISES,
        "description": "在动作库里查动作：做法、要点、常见错误、更容易和更难的替代、什么情况先别做。返回带编号（如 K905）的条目，引用时写这个编号。",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {
                    "type": "string",
                    "description": "动作名或要找的动作类型，如“深蹲”“练背 弹力带”",
                }
            },
            "required": ["query"],
        },
    },
}

# 能调用指标计算的角色（BMI、基础代谢、热量与蛋白质目标、体重趋势、与本人基线的比较）
METRIC_ROLES = frozenset({"trainer", "nutrition", "recovery", "general"})

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
    pro_queries: int = 0  # 专业工具（只算不查，不占查询次数）
    health_failed: bool = False
    # 每次工具调用：哪个工具、结果（ok / empty 查空 / error 失败 / refused 没有权限）、耗时（运行框架用，不含内容）
    calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def queries(self) -> int:
        return self.health_queries + self.knowledge_queries + self.metric_queries

    def absorb(self, other: Evidence) -> None:
        """接力时带上前一层的依据，后一层沿用同样的出处不会被当成编造。"""
        self.support.update(other.support)
        self.entries.update(other.entries)
        self.calcs.update(other.calcs)
        self.rows.update(other.rows)


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


def _step_name(tool: str) -> str:
    if tool in STEP_NAMES:
        return STEP_NAMES[tool]
    from ironm_agent.tool_catalog import CATALOG

    return next((x.title for x in CATALOG if x.agent == tool), "查一下")


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
        calcs: Mapping[str, str] | None = None,
        context: pro.ToolContext | None = None,
        meds: Any | None = None,
        medical: MedicalSearch | None = None,
        extra: Mapping[str, tuple[dict[str, Any], ExtraTool]] | None = None,
    ) -> None:
        self.spec = spec
        # 单 Agent 另加的工具（再装一份 Skill、查 App 用法，spec [2026-10-23] §67）：名字 → (说明, 执行)
        self.extra: dict[str, tuple[dict[str, Any], ExtraTool]] = dict(extra or {})
        self.actions_held = ""  # 这一轮没放进系统提示的计划和记录写法，装训练类规程时补上（§96）
        self.actions: Desk | None = None  # 动作工具：跟着规程一起装（§120），由单 Agent 那一轮给
        self.flags: frozenset[str] = (
            frozenset()
        )  # 这个人的少见情况：再装基础规程时带上对应的规则（§74）
        role = spec.role.value
        self.meds = meds if role in MEDS_ROLES else None  # mirobody 的用药记录工具
        self.medical = medical if role in MEDICAL_ROLES else None  # mirobody 的医学知识
        self.context = context  # 专业工具要用的这个人的情况；没有时不提供专业工具
        self.kb = kb
        self.health = health if spec.health_data else None
        # 共享档案里已经带了全部计算结果（calcs）时，不再提供 compute_metrics 工具，省一轮查询
        self.metrics = metrics if spec.role.value in METRIC_ROLES and calcs is None else None
        self.user_info = {"user_id": user_id, "session_id": session_id}
        self.render = render
        self.evidence = Evidence()
        self.progress: Progress | None = None  # 页面进度（§165）：每开始、做完一步告诉页面
        self._steps = 0
        if calcs:
            self.evidence.calcs.update(calcs)

    @property
    def library(self) -> bool:
        return self.spec.role.value in LIBRARY_ROLES

    def schemas(self) -> list[dict[str, Any]]:
        out = [KNOWLEDGE_SCHEMA] if self.spec.kb_domains else []
        if self.library:
            out.append(EXERCISES_SCHEMA)
        if self.health is not None:
            out.append(_health_schema())
        if self.metrics is not None:
            out.append(METRICS_SCHEMA)
        if self.meds is not None:
            out.append(_meds_schema())
        if self.medical is not None:
            out.append(MEDICAL_SCHEMA)
        if self.context is not None:
            out += [t.schema() for t in pro.tools_for(self.spec.role.value)]
        out += [schema for schema, _ in self.extra.values()]
        if self.actions is not None:
            out += self.actions.schemas()
        return out

    def is_action(self, name: str) -> bool:
        """动作工具（改计划、新计划、记训练）：不占查询次数（§120）。"""
        return self.actions is not None and name in ACTION_TOOLS

    def _exercises(self, query: str) -> str:
        from ironm_agent.exercises import library_kb

        self.evidence.knowledge_queries += 1
        found = library_kb().search(query, {"library"}, k=3)
        for e in found:
            self.evidence.entries[e.id] = e
        if not found:
            self._outcome = "empty"
            return "动作库里没有找到这个动作。"
        return "\n\n".join(e.as_evidence() for e in found)

    def adopt(self, entries: Iterable[Entry]) -> None:
        """把资料记为这一轮可以引用的依据（装载的规程用到的资料）。"""
        for e in entries:
            self.evidence.entries[e.id] = e

    def prefetch(self, query: str, k: int = 3) -> str:
        """作答前先按问题从本领域依据库取出最相关的几条（spec [2026-10-23] §7），不算一次查询；
        能查动作库的角色，问题里点到名字的动作也一起取出来。"""
        found = (
            self.kb.search(query, self.spec.kb_domains, k=k) if self.spec.kb_domains and k else []
        )
        if self.library:
            from ironm_agent.exercises import named_in

            found += named_in(query)
        for e in found:
            self.evidence.entries[e.id] = e
        return "\n\n".join(e.as_evidence() for e in found)

    async def prefetch_health(self, names: Sequence[str]) -> tuple[str, int, bool]:
        """问题里点到的指标，作答前由规则先查一遍最新值（spec [2026-10-23] §37），不占模型的查询次数。
        返回（给模型看的查询结果、查到几行、查询成没成功）。"""
        if self.health is None or not names:
            return "", 0, False
        before = len(self.evidence.support)
        self._outcome = "ok"
        start = time.perf_counter()
        text = await self._health({"keywords": list(names), "view": "latest"})
        self.evidence.health_queries -= 1  # 规则预取：不算模型自己的查询
        ms = int((time.perf_counter() - start) * 1000)
        self.evidence.calls.append({"tool": "prefetch_health", "result": self._outcome, "ms": ms})
        return text, len(self.evidence.support) - before, self._outcome != "error"

    # 这一次工具调用的结果（run 里记下）：放在上下文变量里，几个查询同时跑时各记各的（§165）
    @property
    def _outcome(self) -> str:
        return _OUTCOME.get()

    @_outcome.setter
    def _outcome(self, value: str) -> None:
        _OUTCOME.set(value)

    def step(self, name: str, detail: str = "") -> str | None:
        """告诉页面开始了一步，返回这一步的编号（没接页面时 None）。"""
        if self.progress is None:
            return None
        self._steps += 1
        sid = f"step-{self._steps}"
        self.progress(sid, name, detail[:40], None)
        return sid

    def step_done(self, sid: str | None, ok: bool = True) -> None:
        if sid is not None and self.progress is not None:
            self.progress(sid, "", "", ok)

    async def run(self, call: ToolCall) -> str:
        """执行一次工具调用，并记下结果和耗时（spec [2026-10-23] §31）。"""
        self._outcome = "ok"
        start = time.perf_counter()
        sid = (None if call.name in QUIET_STEPS
               else self.step(_step_name(call.name), str(call.arguments.get("query") or "")))  # fmt: skip
        try:
            return await self._dispatch(call)
        except BaseException:  # 出错或被停下（到了时限）：这一步记成没做完
            self._outcome = "error"
            raise
        finally:
            ms = int((time.perf_counter() - start) * 1000)
            self.evidence.calls.append({"tool": call.name, "result": self._outcome, "ms": ms})
            self.step_done(sid, self._outcome != "error")

    async def _dispatch(self, call: ToolCall) -> str:
        if self.actions is not None and call.name in ACTION_TOOLS:
            return await self.actions.run(call.name, call.arguments)
        if call.name in self.extra:
            return await self.extra[call.name][1](self, call.arguments)
        if call.name == KNOWLEDGE and self.spec.kb_domains:
            return self._knowledge(str(call.arguments.get("query", "")))
        if call.name == EXERCISES and self.library:
            return self._exercises(str(call.arguments.get("query", "")))
        if call.name == HEALTH and self.health is not None:
            return await self._health(call.arguments)
        if call.name == METRICS and self.metrics is not None:
            return await self._metrics()
        if call.name == MEDS and self.meds is not None:
            return await self._meds(call.arguments)
        if call.name == MEDICAL and self.medical is not None:
            return await self._medical(str(call.arguments.get("query", "")))
        if self.context is not None and pro.allowed(self.spec.role.value, call.name):
            return await self._pro(call)
        self._outcome = "refused"
        return json.dumps({"error": f"{self.spec.name}不能使用这个工具"}, ensure_ascii=False)

    async def _pro(self, call: ToolCall) -> str:
        from ironm_agent.exercises import library_entries

        assert self.context is not None
        self.evidence.pro_queries += 1
        result = await pro.run(call.name, self.context, call.arguments)
        if result.plans and self.actions is not None:  # 方案库的草稿：交新计划时可以只写方案编号和改法（§165）
            self.actions.template_plans.update(result.plans)
        return pro.render(
            result,
            role=self.spec.role.value,
            calcs=self.evidence.calcs,
            entries=self.evidence.entries,
            library={e.id: e for e in library_entries()},
        )

    async def _metrics(self) -> str:
        self.evidence.metric_queries += 1
        try:
            items = await self.metrics()  # type: ignore[misc]
        except Exception as e:
            _log.warning("metrics failed: error_type=%s", type(e).__name__)
            self._outcome = "error"
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

    async def _meds(self, args: Mapping[str, Any]) -> str:
        self.evidence.health_queries += 1
        try:
            out = await self.meds.query_medications(self.user_info, **dict(args))  # type: ignore[union-attr]
        except Exception as e:  # 读不到不影响作答
            _log.warning("medications query failed: error_type=%s", type(e).__name__)
            self._outcome = "error"
            return "这次没能读取用药记录。"
        if isinstance(out, Mapping) and out.get("success") is False:
            self._outcome = "error"
            return "用药记录查询没有成功，可以如实说明没读到。"
        text = out.get("result") if isinstance(out, Mapping) else out
        return str(text or "没有用药记录。")

    async def _medical(self, query: str) -> str:
        self.evidence.knowledge_queries += 1
        try:
            return await self.medical(query, "")  # type: ignore[misc]
        except Exception as e:
            _log.warning("medical knowledge failed: error_type=%s", type(e).__name__)
            self._outcome = "error"
            return "这次没能查到医学资料。"

    def _knowledge(self, query: str) -> str:
        self.evidence.knowledge_queries += 1
        found = self.kb.search(query, self.spec.kb_domains)
        for e in found:
            self.evidence.entries[e.id] = e
        if not found:
            self._outcome = "empty"
            return "依据库里没有找到相关资料。"
        return "\n\n".join(e.as_evidence() for e in found)

    async def _health(self, args: Mapping[str, Any]) -> str:
        self.evidence.health_queries += 1
        try:
            envelope = await self.health.envelope(self.user_info, **dict(args))  # type: ignore[union-attr]
        except Exception as e:  # 读不到数据不影响作答：如实告诉模型
            _log.warning("health query failed: error_type=%s", type(e).__name__)
            self.evidence.health_failed = True
            self._outcome = "error"
            return "这次没能读取健康数据。"
        if getattr(envelope, "status", "ok") == "error":
            self.evidence.health_failed = True
            kind = getattr(envelope, "error_kind", None) or "error"
            self._outcome = "error"
            return f"查询没有成功（{kind}），可以换个参数再试，或者如实说明没读到数据。"
        rows = getattr(envelope, "data", None) or []
        if not rows:
            self._outcome = "empty"
        for row in rows:
            rid = row.get("rid") if isinstance(row, Mapping) else None
            if isinstance(rid, str) and rid:
                self.evidence.support[rid] = row_numbers(row)
                self.evidence.rows[rid] = row_label(row)
        return self.render(envelope)
