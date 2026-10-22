"""iron-m 的 Agent：通过 mirobody 的 Agent 插件接口替换它自带的 Agent。

一轮回答：安全前置（规则）→ 读这个人的记忆 → 主教练理解与调度 → 专业 Agent 同时作答（互不可见）
→ 主教练整合 → 规则核对；回答发出后在后台提取这一轮的记忆（不拖慢回答，失败也不影响回答）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping
from functools import cache
from typing import Any

from ironm_agent.coach import direct
from ironm_agent.compose import compose
from ironm_agent.experts import Consultation, consult
from ironm_agent.kb import KnowledgeBase, default_kb
from ironm_agent.llm import ModelsConfig, TurnLLM, load_models
from ironm_agent.memory import last_sources, recent, user_lines
from ironm_agent.memory_extract import extract
from ironm_agent.memory_store import MemoryStore, default_store
from ironm_agent.memory_view import Recall
from ironm_agent.personal import personal_basics
from ironm_agent.provenance import explain, is_provenance
from ironm_agent.render import (
    SOURCES_ID,
    SOURCES_NAME,
    answer_text,
    consultation_summary,
    finished,
    notice,
    sections_text,
    sources_text,
    started,
    text_block,
)
from ironm_agent.roles import SPECS
from ironm_agent.router import Route, route
from ironm_agent.safety.emergency import assess
from ironm_agent.safety.refusals import default_refusals
from ironm_agent.safety.replies import (
    REPLIES_PATH,
    Replies,
    four_section,
    load_replies,
    refusal_sections,
)
from ironm_agent.tools import Toolbox

_log = logging.getLogger("ironm_agent.run")

FAILED = "IronM 这次没能回答，请稍后再试。"
NO_TEXT = "没有收到文字问题。"
NO_ANSWER = "这次没能调用模型，暂时回答不了，请稍后再试。"


@cache
def _replies() -> Replies:
    return load_replies(REPLIES_PATH)


def question_of(messages: list[dict[str, Any]]) -> str:
    """取出本轮的文字：内容是字符串就直接用；是多段内容就拼接其中的文字段。"""
    if not messages:
        return ""
    content = messages[-1].get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            p.get("text", "") for p in content if isinstance(p, Mapping) and p.get("type") == "text"
        ]
        return "".join(str(p) for p in parts).strip()
    return ""


def route_summary(r: Route) -> str:
    if r.intent != "pro":
        kinds = {"chat": "闲聊", "app": "问 App 用法", "out_of_scope": "超出范围"}
        return f"判断为{kinds[r.intent]}，由主教练直接回答"
    names = "、".join(SPECS[x].name for x in r.experts())
    how = "模型判断" if r.by == "model" else "按关键词（" + "；".join(r.problems) + "）"
    return f"请了：{names}\n方式：{how}" + (f"\n理由：{r.reason}" if r.reason else "")


class IronMAgent:
    """mirobody 的 Agent 槽位：同一个进程只有这一个 Agent。"""

    def __init__(
        self,
        *,
        health: Any | None = None,
        kb: KnowledgeBase | None = None,
        models: ModelsConfig | None = None,
        environ: Mapping[str, str] | None = None,
        metrics: Callable[[str], Awaitable[list[Any]]] | None = None,
        memory: MemoryStore | None = None,
        **kwargs: Any,
    ) -> None:
        self._metrics = metrics  # 按用户计算指标（默认与数据页同一份计算）
        self._memory = memory  # 长期记忆（默认用数据库里 iron-m 自己的表）
        self._locks: dict[str, asyncio.Lock] = {}  # 同一个人的记忆提取一次只跑一个
        self._tasks: set[asyncio.Task[None]] = set()  # 后台提取记忆的任务
        self._health = health
        self._kb = kb or default_kb()
        self._models = models or load_models()
        self._environ = environ if environ is not None else os.environ

    @classmethod
    def load_llm_clients(cls, models: dict[str, Any]) -> dict[str, Any]:
        """告诉 mirobody 网页可以选哪些模型。

        mirobody 的网页先取 /api/models 的第一项作为默认模型，列表为空就无法提问；这个列表由这里
        返回的名字决定。iron-m 实际用哪个模型由 config/models.yaml 按环节配置，与网页上选哪项无关，
        所以只报和我们用同一个密钥的那几项（都没有时报全部，保证网页能提问）。
        """
        ours = load_models().stages["compose"].api_key_env
        same = {
            n: "iron-m"
            for n, e in models.items()
            if isinstance(e, Mapping) and e.get("api_key") == ours
        }
        return same or dict.fromkeys(models, "iron-m")

    def _metrics_source(self, user_id: str) -> Callable[[], Awaitable[list[Any]]]:
        """这一轮的指标：第一次被调用时计算，同一轮里各 Agent 共用结果。"""
        compute = self._metrics
        if compute is None:
            from ironm_agent.web import metrics_for

            async def default(uid: str) -> list[Any]:
                return list((await metrics_for(uid))[0])

            compute = default
        result: list[Any] | None = None
        lock = asyncio.Lock()

        async def once() -> list[Any]:
            nonlocal result
            async with lock:
                if result is None:
                    result = await compute(user_id)
                return result

        return once

    def _memory_store(self) -> MemoryStore:
        if self._memory is None:
            self._memory = default_store()
        return self._memory

    async def _recall(self, user_id: str) -> Recall:
        """作答前读这个人的全部有效记忆；读不到时当作没有记忆，不影响作答。"""
        try:
            return Recall.of(await self._memory_store().items(user_id))
        except Exception as e:
            _log.warning("memory unavailable: error_type=%s", type(e).__name__)
            return Recall()

    async def _remember(self, user_id: str, text: str, answer: str, context: list[str]) -> None:
        """回答发出后提取这一轮的记忆；暂停记忆时不提取。日志只记条数和耗时，不记内容。"""
        start = time.perf_counter()
        store = self._memory_store()
        try:
            async with self._locks.setdefault(user_id, asyncio.Lock()):
                if await store.paused(user_id):
                    return
                items = await store.items(user_id)
                llm = TurnLLM(self._models, self._environ)
                out = await extract(llm, items, text, answer, context)
                await store.apply(user_id, out.changes)
        except Exception as e:  # 提取失败不影响已经发出的回答
            _log.warning("memory extraction failed: error_type=%s", type(e).__name__)
            return
        stats = {
            "inserted": sum(1 for c in out.changes if c.kind == "insert"),
            "superseded": sum(1 for c in out.changes if c.kind == "status"),
            "rejected": len(out.rejected),
            "failed": bool(out.failed),
            "ms": int((time.perf_counter() - start) * 1000),
        }
        _log.info("ironm memory %s", json.dumps(stats))

    async def settle(self) -> None:
        """等后台的记忆提取做完（测试与停机时用）。"""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    def _health_source(self) -> Any:
        if self._health is None:
            from mirobody.agent.tools.health_indicators_service import HealthIndicatorsService

            self._health = HealthIndicatorsService()
        return self._health

    async def generate_response(
        self,
        user_id: str,
        messages: list[dict[str, Any]],
        language: str = "",
        session_id: str = "",
        file_list: list[dict[str, Any]] | None = None,
        provider: str = "",
        prompt_name: str = "",
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any]]:
        run: dict[str, Any] = {"turn": uuid.uuid4().hex[:12], "path": "error"}
        start = time.perf_counter()
        llm = TurnLLM(self._models, self._environ)
        said: dict[str, Any] = {}  # 这一轮的回答（交给后台提取记忆，不进日志）
        try:
            text = question_of(messages)
            if not text:
                run["path"] = "no_text"
                yield notice(NO_TEXT)
                return
            async for block in self._turn(user_id, session_id, text, llm, run, said):
                yield block
            if "answer" in said:
                task = asyncio.create_task(
                    self._remember(user_id, text, said["answer"], user_lines(said["history"]))
                )
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
        except Exception as e:  # 不把异常原文给用户
            _log.error("turn failed: error_type=%s", type(e).__name__)
            run["error_type"] = type(e).__name__
            yield {"type": "error", "message": FAILED}
        finally:
            run["ms"] = int((time.perf_counter() - start) * 1000)
            run["model_calls"] = len(llm.calls)
            run["model_failures"] = sum(1 for c in llm.calls if not c.ok)
            # 耗时放在前面：mirobody 会截断过长的日志行
            first = ("turn", "path", "ms", "memory", "memory_ms", "model_calls", "model_failures")
            ordered = {k: run[k] for k in first if k in run} | run
            _log.info("ironm turn %s", json.dumps(ordered, ensure_ascii=False))

    async def _turn(
        self,
        user_id: str,
        session_id: str,
        text: str,
        llm: TurnLLM,
        run: dict[str, Any],
        said: dict[str, Any],
    ) -> AsyncGenerator[dict[str, Any]]:
        # 1. 安全前置：只用规则；急症与红旗直接给固定回答，不调用模型
        assessment = assess(text)
        refusals = default_refusals().detect(text)
        replies = _replies()
        run["safety"] = assessment.level
        run["refusals"] = list(refusals.kinds)
        if assessment.level != "none":
            run["path"] = "safety"
            sections = four_section(replies, assessment) + refusal_sections(replies, refusals.kinds)
            yield text_block(sections_text(sections))
            return
        prefix = sections_text(refusal_sections(replies, refusals.kinds)) if refusals.kinds else ""

        # 追问上一条回答的来源：直接从“依据与来源”里讲，不再请专业 Agent
        if is_provenance(text):
            run["path"] = "provenance"
            yield text_block(explain(text, await last_sources(session_id, SOURCES_ID)))
            return

        # 2. 读这个人的记忆（全部有效记忆，不靠检索）；主教练理解与调度
        history = await recent(session_id, text)
        read = time.perf_counter()
        recall = await self._recall(user_id)
        run["memory"] = len(recall.items)
        run["memory_ms"] = int((time.perf_counter() - read) * 1000)
        said["history"] = history
        r = await route(text, history, llm, recall.persona())
        run.update(intent=r.intent, route_by=r.by, concerns=list(r.concerns))
        for block in (
            started("coach", "主教练", "理解问题、安排专业角色"),
            finished("coach", route_summary(r)),
        ):
            yield block
        if r.intent != "pro" or r.primary is None:
            run["path"] = "direct"
            answer = await direct(r.intent, text, history, llm, recall.persona())
            said["answer"] = answer
            yield text_block("\n\n".join(x for x in (prefix, answer) if x))
            return

        # 3. 专业 Agent 同时作答，互不可见；谁先答完先显示。先读这个人最新的体重、身高，大家都能按本人算
        personal = await personal_basics(self._health_source(), user_id, session_id)
        run["basics"] = len(personal.lines)
        roles = r.experts()
        run["roles"] = [x.value for x in roles]
        if recall.items:  # 记忆不在前端显示；各角色拿到哪几类只写进日志（只有类别，不含内容）
            used = {x.value: recall.categories_for(x) for x in roles}
            _log.info("ironm memory use %s", json.dumps({"turn": run["turn"], "roles": used}))
        metrics_once = self._metrics_source(user_id)
        tasks: dict[asyncio.Task[Consultation], int] = {}
        for i, role in enumerate(roles):
            spec = SPECS[role]
            yield started(f"role-{i}", spec.name, spec.duty)
            toolbox = Toolbox(
                spec,
                kb=self._kb,
                health=self._health_source() if spec.health_data else None,
                user_id=user_id,
                session_id=session_id,
                metrics=metrics_once,
            )
            task = asyncio.create_task(
                consult(spec, text, history, r.concerns, toolbox, llm, personal, recall)
            )
            tasks[task] = i
        results: dict[int, Consultation] = {}
        pending: set[asyncio.Task[Consultation]] = set(tasks)
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                i = tasks[task]
                results[i] = task.result()
                yield finished(
                    f"role-{i}", consultation_summary(results[i]), ok=results[i].status != "failed"
                )
        consultations = [results[i] for i in range(len(roles))]
        run["statuses"] = [c.status for c in consultations]
        run["queries"] = sum(c.evidence.queries for c in consultations)
        if any(c.evidence.health_failed for c in consultations):
            yield notice("这次没读到你的健康数据，下面的回答没有用到它。")

        # 4. 主教练整合，5. 规则核对
        if not any(c.opinion.speak for c in consultations):
            run["path"] = "no_answer"
            said["answer"] = ""  # 没能回答，也要记下用户这句话里说到的情况
            yield text_block("\n\n".join(x for x in (prefix, NO_ANSWER) if x))
            return
        composed = await compose(text, r.primary, consultations, llm, recall)
        run.update(path="answer", degraded=composed.degraded, rewrites=composed.rewrites,
                   kb=[e.id for e in composed.entries])  # fmt: skip
        if composed.degraded:
            yield notice("这次回答受限：整合没有通过核对，下面给出主责角色核对过的意见。")
        said["answer"] = answer_text(composed)
        yield text_block(answer_text(composed, prefix=prefix))
        sources = sources_text(composed)
        if sources:  # 出处不写进正文，放进可展开的“依据与来源”
            yield started(SOURCES_ID, SOURCES_NAME, "这条回答用到的资料、计算和你的数据")
            yield finished(SOURCES_ID, sources)
