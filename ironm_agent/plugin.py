"""iron-m 的 Agent：通过 mirobody 的 Agent 插件接口替换它自带的 Agent。

一轮回答：安全前置（规则）→ 读这个人的记忆 → 三路打分路由（模型、关键字、语义向量）→ 专业 Agent 分层作答
→ 只请一位时它直接作答、多位时由管家整合 → 规则核对；回答发出后在后台提取这一轮的记忆（不拖慢回答，失败也不影响回答）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from functools import cache
from typing import Any, Literal

from ironm_agent.attachments import Attachments
from ironm_agent.attachments import read as read_attachments
from ironm_agent.casefile import CaseFile, Snapshot
from ironm_agent.casefile import build as build_case
from ironm_agent.checks import plain
from ironm_agent.clarify import PLAN_REQUEST, Decision, asked, decide
from ironm_agent.coach import direct
from ironm_agent.compose import Composed, compose, revise
from ironm_agent.constraints import Context, Violation, annotate, annotate_plan
from ironm_agent.constraints import check as check_constraints
from ironm_agent.exercises import named_in
from ironm_agent.experts import Consultation, consult, write_task
from ironm_agent.harness import TraceStore, mentioned_roles, missing_readings, new_turn, react
from ironm_agent.indicators import kinds_of, named_indicators
from ironm_agent.kb import KnowledgeBase, default_kb
from ironm_agent.llm import ModelsConfig, TurnLLM, load_models
from ironm_agent.memory import USER, earlier, last_sources, recent, split_thread, user_lines
from ironm_agent.memory_extract import extract, hold, take_held, worth_extracting
from ironm_agent.memory_prefs import due as prefs_due
from ironm_agent.memory_prefs import refresh as refresh_prefs
from ironm_agent.memory_store import MemoryStore, default_store
from ironm_agent.memory_view import Recall
from ironm_agent.personal import Personal, personal_basics
from ironm_agent.progression import target_lines
from ironm_agent.protools.plan_check import check_plan
from ironm_agent.protools.registry import ToolContext
from ironm_agent.provenance import explain, is_provenance
from ironm_agent.render import (
    SOURCES_ID,
    SOURCES_NAME,
    TURN_ID,
    answer_text,
    consultation_summary,
    finished,
    log_card,
    notice,
    plan_card,
    sections_text,
    sources_text,
    started,
    text_block,
)
from ironm_agent.roles import Role, spec_of
from ironm_agent.router import MAX_HELPERS, Route, concerns_of, keyword_route
from ironm_agent.routing import Decision as RouteDecision
from ironm_agent.routing import default_router
from ironm_agent.safety.emergency import assess
from ironm_agent.safety.refusals import default_refusals
from ironm_agent.safety.replies import (
    REPLIES_PATH,
    Replies,
    four_section,
    load_replies,
    refusal_sections,
)
from ironm_agent.skills import choose
from ironm_agent.tools import Evidence, Toolbox
from ironm_agent.training import (
    Plan,
    TrainingStore,
    WorkoutLog,
    case_lines,
    default_training,
    log_content,
    parse_log,
    parse_plan,
    plan_content,
    task_of,
    trusted_log,
)
from ironm_agent.triggers import PainStore, default_pain, pain_parts
from ironm_agent.weather import Weather
from ironm_agent.weather import case_line as weather_line
from ironm_agent.weather import for_user as weather_for

_log = logging.getLogger("ironm_agent.run")

FAILED = "IronM 这次没能回答，请稍后再试。"
REVIEW_ASK = "按这周的复盘调整训练计划"  # 每周复盘一键生成调整方案时的问法（spec [2026-10-23] §18）
REVIEW_MAX_DAYS = 2  # 按复盘调整每次最多改几天
WEATHER_WAIT_S = 4.0  # 天气最多等 4 秒（同一个地方 10 分钟内有缓存）
NO_TEXT = "没有收到文字问题。"
NO_ANSWER = "这次没能调用模型，暂时回答不了，请稍后再试。"
# 不做关爱圈（项目负责人决定）：提问人和数据的主人不是同一个人时，不读写对方的数据和记忆
HELP_ASK = "IronM 只回答你自己的问题，暂不支持替别人提问或查看别人的数据。"


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


async def default_coach_eval(user_id: str, reason: str, force: bool) -> None:
    """管家重新评估当前方案，用线上的存储（测试里换掉）。"""
    from ironm_agent.coach_state import evaluate
    from ironm_agent.web_more import coach_deps

    await evaluate(user_id, coach_deps(), reason=reason, force=force)


# 分层接力（spec [2026-10-23] §3、§20）：先评估身体状态，再出训练和饮食方案，后一层拿到前一层的结论
LAYERS: tuple[frozenset[Role], ...] = (
    frozenset({Role.RECOVERY}),
    frozenset({Role.TRAINER, Role.NUTRITION, Role.GENERAL}),
)
TRAINING_ROLES = frozenset({Role.TRAINER})  # 请到它就是在问训练（康复恢复师也管睡眠，不算）
_TRAINING = re.compile(r"练|训练|运动|健身|跑|深蹲|卧推|硬拉|动作|计划")
RISK_BLOCK = "这一轮先不给训练安排。饮食、睡眠或者你的数据，可以照常问我。"
CONFIRM_NOTE = {
    "plan": "下面是计划预览，点「确认」才会保存，保存后也能撤销。",
    "log": "下面是这次训练的记录预览，点「确认」才会记下。",
}
_FOOD = re.compile(r"热量|卡路里|千卡|吃|这顿|这餐|一餐|蛋白|营养|食物|饭|菜")
# 明显在问训练的说法：先用规则看要不要拦下或追问，不必等调度（"练完吃什么"不算）
_TRAIN_ASK = re.compile(
    r"练什么|怎么练|练啥|还能练|能练|能不能练|去练|练腿|练胸|练背|练肩|练手|练臀|练核心|训练计划|训练安排"
    r"|健身|锻炼|跑步|深蹲|卧推|硬拉|有氧|力量|大重量|课表"
)
_NOT_TRAINING = re.compile(
    r"吃|喝|饮食|热量|蛋白|睡|失眠"
)  # "运动后吃什么""睡不好怎么办"不是在问训练


def asks_training(text: str) -> bool:
    return bool(_TRAIN_ASK.search(text)) and not _NOT_TRAINING.search(text)


@dataclass(frozen=True)
class Prepared:
    snapshot: Snapshot
    plan: Plan | None
    case: CaseFile
    decision: Decision


def _weather_case(w: Weather, plan: Plan | None, today: date) -> str:
    """共享档案里的天气（spec [2026-10-23] §34）：现在的天气、未来几天的预报、按天气对本周训练的调整。"""
    from ironm_agent.weather import assess
    from ironm_agent.weather_plan import forecast_line, line, week_plan

    parts = [weather_line(w)]
    ahead = forecast_line(w.days, today)
    if ahead:
        parts.append(f"未来几天：{ahead}")
    moved = [
        line(p) for p in week_plan(plan, w.days, today, assess(w)) if p.day > today and p.adjusted
    ]
    if moved:
        parts.append("按天气对本周训练的调整：" + "；".join(moved))
    return "。".join(parts)


_HURT = re.compile(r"疼|痛|伤|肿|麻|酸|不舒服|难受")


def checked_note(named: Sequence[str], found: str, rows: int, ok: bool) -> str:
    """规则先查的结果，交给专业角色时怎么说（spec [2026-10-23] §37）。"""
    names = "、".join(named)
    if not ok:
        return (
            f"系统想先查这个人的{names}记录，但这次没能读到健康记录：如实说这次没读到，不推测高低。"
        )
    if rows == 0:
        return (f"系统按问题先查了这个人的健康记录，没有找到{names}的记录。回答的第一句就如实说没有找到这项记录，"
                "不推测高低，也不要当作已经偏高或偏低去安排训练和饮食；告诉他可以在数据页上传化验单或随手记一条。")  # fmt: skip
    return (f"系统按问题先查了这个人的健康记录（{names}）：\n{found}\n"
            "回答的第一句先说他问的这几项：数值、日期，和这里给的参考范围比是偏高、偏低还是在范围内，每项只说一次，"
            "写成：<statement>你的空腹血糖 5.1 mmol/L（2025-11-12），参考范围 3.9–6.1<cite>[r1]</cite></statement>，在范围内。"
            "（例子里的数字只是示范，照上面查到的行写，编号用那一行的。）"
            "这里没有出现的指标就是没有记录，如实说没有。说出数值和参考范围不算诊断。")  # fmt: skip


def layers_of(roles: Sequence[Role]) -> list[list[Role]]:
    return [[r for r in roles if r in layer] for layer in LAYERS if any(r in layer for r in roles)]


def relay_text(before: Sequence[Consultation]) -> str:
    """前一层同事的结论（带着出处标记，后一层沿用同样的出处）。"""
    lines = []
    for c in before:
        o = c.opinion
        if not o.speak:
            continue
        parts = [
            o.conclusion or o.answer,
            o.how and f"做法：{o.how}",
            o.caution and f"注意：{o.caution}",
        ]
        lines.append(f"- {spec_of(o.role).name}：" + "；".join(x for x in parts if x))
    if not lines:
        return ""
    return (
        "前面同事的结论（你的建议要和它一致，冲突时以安全和恢复为准；用到里面的数字时带上同样的编号）：\n"
        + "\n".join(lines)
    )


CHANNEL_NAMES = {"llm": "模型", "keyword": "关键字", "vector": "语义向量"}


def as_route(d: RouteDecision) -> Route:
    """三路打分的结果（spec [2026-10-23] §16）转成作答链路用的调度结果。"""
    used = "、".join(f"{CHANNEL_NAMES[c]} {w:.1f}" for c, w in d.weights.items())
    top = "、".join(f"{spec_of(x).name} {d.weighted[x.value]:.2f}" for x in d.roles)
    return Route(
        intent=d.intent,
        concerns=d.concerns,  # type: ignore[arg-type]
        primary=d.primary,
        helpers=d.roles[1:],
        reason=f"加权得分：{top}" if top else "",
        by="weighted",
        problems=(f"权重：{used}",) if used else (),
        skills=d.skills,
    )


def route_summary(r: Route) -> str:
    if r.intent != "pro":
        kinds = {"chat": "闲聊", "app": "问 App 用法", "out_of_scope": "超出范围"}
        return f"判断为{kinds[r.intent]}，由管家直接回答"
    names = "、".join(spec_of(x).name for x in r.experts())
    if r.by == "weighted":
        how = "模型、关键字、语义向量三路打分（" + "；".join(r.problems) + "）"
    elif r.by == "model":
        how = "模型判断"
    else:
        how = "按关键词（" + "；".join(r.problems) + "）"
    return f"请了：{names}\n方式：{how}" + (f"\n{r.reason}" if r.reason else "")


class IronMAgent:
    """mirobody 的 Agent 槽位：同一个进程只有这一个 Agent。"""

    def __init__(
        self,
        *,
        health: Any | None = None,
        kb: KnowledgeBase | None = None,
        models: ModelsConfig | None = None,
        environ: Mapping[str, str] | None = None,
        snapshot: Callable[[str], Awaitable[Snapshot]] | None = None,
        files: Mapping[str, Any] | None = None,
        memory: MemoryStore | None = None,
        training: TrainingStore | None = None,
        history: Callable[[str, str], Awaitable[list[str]]] | None = None,
        earlier: Callable[[str], Awaitable[str]] | None = None,
        sources: Callable[[str, str], Awaitable[str | None]] | None = None,
        remember: bool = True,
        mode: Literal["multi", "single"] = "multi",
        observe: Callable[[dict[str, Any]], None] | None = None,
        weather: Callable[[str], Awaitable[Weather | None]] | None = None,
        pain: PainStore | None = None,
        medications: Any | None = None,
        medical: Any | None = None,
        traces: TraceStore | None = None,
        **kwargs: Any,
    ) -> None:
        self._traces = (
            traces  # 运行框架的轨迹（spec [2026-10-23] §31，默认用数据库里 iron-m 自己的表）
        )
        # mirobody 的用药记录与医学知识（spec [2026-10-23] §25）；测试时换成假的，注入了 health 却没给的不用
        self._meds = medications
        self._medical = medical
        self._pain = pain  # 说疼的部位和日期（触发型调整用，默认用数据库里 iron-m 自己的表）
        self._weather = weather  # 这个人所在城市的天气（默认按"我的"里设置的城市去取）
        self._snapshot = snapshot  # 这个人的档案、健康数据与指标（默认与数据页同一份计算）
        self._files: dict[str, Any] = dict(files or {})  # 读附件的方式（测试时换成假的）
        self._memory = memory  # 长期记忆（默认用数据库里 iron-m 自己的表）
        self._training = training  # 训练计划、训练记录与预览（默认用数据库里 iron-m 自己的表）
        # 以下几项给考题用：本会话前几轮、上一条回答的来源（默认读 mirobody 的对话记录）、
        # 回答后是否提取记忆、架构（multi 正式版 / single 单 Agent 对照组）、每轮结束时拿到运行记录
        self._history = history
        self._earlier = earlier
        self._sources = sources
        self._remember_on = remember
        self._mode = mode
        self._observe = observe
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

    async def _read_snapshot(self, user_id: str) -> Snapshot:
        """这一轮读一次这个人的数据（共享档案用）；读不到时当作没有数据，不影响作答。"""
        source = self._snapshot
        if source is None:
            from ironm_agent.web import snapshot_for

            source = snapshot_for
        try:
            return await source(user_id)
        except Exception as e:
            _log.warning("snapshot unavailable: error_type=%s", type(e).__name__)
            return Snapshot(failed=True)

    def _tool_context(
        self, user_id: str, snapshot: Snapshot, case: CaseFile, recall: Recall
    ) -> ToolContext:
        """专业工具要用的这个人的情况（spec [2026-10-23] §12）；训练计划与记录在工具用到时才读。"""
        store = self._training_store()

        async def workouts(since: date) -> list[WorkoutLog]:
            return [x.log for x in await store.workouts(user_id, since)]

        weight = snapshot.readings.weight
        return ToolContext.build(
            snapshot.today,
            goal=snapshot.profile.goal,
            weight_kg=max(weight, key=lambda p: p[0])[1] if weight else None,
            kcal_target=next(
                (m.value for m in snapshot.metrics if m.key == "kcal_target" and m.value), None
            ),
            readings=snapshot.readings,
            injured=case.injuries,
            equipment_said=[
                x.content
                for x in recall.items
                if x.category == "equipment" and x.status == "active"
            ],
            plan=lambda: store.plan(user_id),
            workouts=workouts,
        )

    async def _read_weather(self, user_id: str) -> Weather | None:
        """天气取不到或太慢时当作没有，不影响作答（spec [2026-10-23] §13）。"""
        source = self._weather or weather_for
        try:
            return await asyncio.wait_for(source(user_id), WEATHER_WAIT_S)
        except Exception as e:
            _log.warning("weather unavailable: error_type=%s", type(e).__name__)
            return None

    def _pain_store(self) -> PainStore:
        if self._pain is None:
            self._pain = default_pain()
        return self._pain

    async def _coach(self, user_id: str, reason: str, force: bool) -> None:
        """管家重新评估当前方案（spec [2026-10-23] §23）；出错不影响已经发出的回答。"""
        try:
            await default_coach_eval(user_id, reason, force)
        except Exception as e:
            _log.warning("coach evaluate failed: error_type=%s", type(e).__name__)

    async def _record_pain(self, user_id: str, parts: list[str]) -> None:
        """记下这句话里说疼的部位（spec [2026-10-23] §18 需求 5）；暂停记忆时不记。"""
        try:
            if await self._memory_store().paused(user_id):
                return
            for part in parts:
                await self._pain_store().add(user_id, part, date.today())
        except Exception as e:  # 出错不影响已经发出的回答
            _log.warning("pain record failed: error_type=%s", type(e).__name__)
            return
        await self._coach(user_id, "说疼", True)

    def _training_store(self) -> TrainingStore:
        if self._training is None:
            self._training = default_training()
        return self._training

    async def _read_training(
        self, user_id: str, today: date
    ) -> tuple[Plan | None, list[WorkoutLog], date | None]:
        """当前计划、最近两周的训练记录、计划从哪天开始用；读不到时当作没有，不影响作答。"""
        store = self._training_store()
        try:
            plan, logs = await asyncio.gather(
                store.plan(user_id), store.workouts(user_id, today - timedelta(days=14))
            )
        except Exception as e:
            _log.warning("training unavailable: error_type=%s", type(e).__name__)
            return None, [], None
        since = plan.since if plan else None
        return (plan.plan if plan else None), [x.log for x in logs], since

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

    async def _remember(
        self, user_id: str, text: str, answer: str, context: list[str], held: Sequence[str] = ()
    ) -> None:
        """回答发出后提取这一轮的记忆；暂停记忆时不提取。日志只记条数和耗时，不记内容。"""
        start = time.perf_counter()
        store = self._memory_store()
        try:
            async with self._locks.setdefault(user_id, asyncio.Lock()):
                if await store.paused(user_id):
                    return
                items = await store.items(user_id)
                llm = TurnLLM(self._models, self._environ)
                out = await extract(llm, items, text, answer, context, held)
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

    async def _refresh_prefs(self, user_id: str) -> None:
        try:
            await refresh_prefs(user_id, self._memory_store(), self._training_store())
        except Exception as e:  # 出错不影响已经发出的回答
            _log.warning("prefs refresh failed: error_type=%s", type(e).__name__)

    async def settle(self) -> None:
        """等后台的记忆提取做完（测试与停机时用）。"""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    def _meds_source(self) -> Any | None:
        if self._meds is None and self._health is None:  # 线上：用 mirobody 的用药记录工具
            from mirobody.agent.tools.medications_service import MedicationsService

            self._meds = MedicationsService()
        return self._meds

    def _medical_source(self) -> Any | None:
        """部署配置了医学知识（离线索引或联网）时才有。"""
        if self._medical is not None:
            return self._medical
        try:
            from mirobody.agent.knowledge import tools as medical

            return medical.search if medical.scopes() else None
        except Exception as e:
            _log.warning("medical knowledge unavailable: error_type=%s", type(e).__name__)
            return None

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
        # 这一轮的编号：页面上点"有用 / 没用"时带回来，评价记到这一轮的轨迹上（spec [2026-10-23] §31）
        yield {"type": "tool_call", "id": TURN_ID, "name": "", "args": {"turn": run["turn"]}}
        yield {"type": "tool_result", "tool_call_id": TURN_ID, "content": "", "status": "ok"}
        try:
            text = question_of(messages)
            if not text:
                run["path"] = "no_text"
                yield notice(NO_TEXT)
                return
            async for block in self._turn(user_id, session_id, text, llm, run, said, file_list):
                yield block
            if "answer" in said and self._remember_on:
                if worth_extracting(text, run.get("task")):  # 按需提取（spec [2026-10-23] §17）
                    held = take_held(session_id)
                    task = asyncio.create_task(
                        self._remember(
                            user_id, text, said["answer"], user_lines(said["history"]), held
                        )
                    )
                    self._tasks.add(task)
                    task.add_done_callback(self._tasks.discard)
                else:
                    hold(session_id, text)
                    run["memory_extract"] = "skipped"
                if parts := pain_parts(text):  # 说疼的部位：触发型调整用
                    run["pain_parts"] = len(parts)
                    task = asyncio.create_task(self._record_pain(user_id, parts))
                    self._tasks.add(task)
                    task.add_done_callback(self._tasks.discard)
                task = asyncio.create_task(self._coach(user_id, "每天第一次提问", False))
                self._tasks.add(task)  # 每天第一次提问时管家评估一次（今天评估过就不再算）
                task.add_done_callback(self._tasks.discard)
                if prefs_due(user_id):  # 每天第一次回答之后，后台更新训练记录得出的偏好
                    task = asyncio.create_task(self._refresh_prefs(user_id))
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
            run["budget_hit"] = len(llm.calls) >= self._models.turn_budget
            # 耗时放在前面：mirobody 会截断过长的日志行；各环节明细（_ 开头）只进轨迹，不进日志
            first = ("turn", "path", "ms", "memory", "memory_ms", "model_calls", "model_failures")
            ordered = {k: run[k] for k in first if k in run} | run
            line = {k: v for k, v in ordered.items() if not k.startswith("_")}
            _log.info("ironm turn %s", json.dumps(line, ensure_ascii=False))
            if self._observe is not None:
                self._observe(dict(ordered))
            if run["path"] != "no_text":
                task = asyncio.create_task(self._save_trace(user_id, session_id, dict(ordered)))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

    def _trace_store(self) -> TraceStore:
        if self._traces is None:
            from ironm_agent.harness import default_traces

            self._traces = default_traces()
        return self._traces

    async def _save_trace(self, user_id: str, session_id: str, run: dict[str, Any]) -> None:
        """后台存这一轮的轨迹（spec [2026-10-23] §31）；失败只记日志，不影响回答。"""
        try:
            turn = new_turn(user_id, session_id, run)
            await self._trace_store().add(turn)
        except Exception as e:
            _log.warning("trace save failed: error_type=%s", type(e).__name__)

    async def _react(self, user_id: str, session_id: str, text: str, history: list[str]) -> None:
        """这句话是对上一轮的反应（说不对、换个说法再问）时，记到上一轮的轨迹上。"""
        previous = next((x[len(USER) :] for x in reversed(history) if x.startswith(USER)), None)
        try:
            await react(self._trace_store(), user_id, session_id, text, previous)
        except Exception as e:
            _log.warning("trace react failed: error_type=%s", type(e).__name__)

    async def _turn(
        self,
        user_id: str,
        session_id: str,
        text: str,
        llm: TurnLLM,
        run: dict[str, Any],
        said: dict[str, Any],
        file_list: list[dict[str, Any]] | None = None,
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

        asker, _ = split_thread(session_id)
        if asker and asker != user_id:  # 关爱圈里替别人问：只说明不支持
            run["path"] = "help_ask"
            yield text_block(HELP_ASK)
            return

        # 追问上一条回答的来源：直接从“依据与来源”里讲，不再请专业 Agent
        if is_provenance(text):
            run["path"] = "provenance"
            sources = await (self._sources or last_sources)(session_id, SOURCES_ID)
            yield text_block(explain(text, sources))
            return

        # 2. 读本会话前几轮与这个人的记忆（全部有效记忆，不靠检索）；同时开始读他的数据（档案、健康数据、
        #    指标），与路由并行（spec [2026-10-23] §7）
        read = time.perf_counter()
        history, recall = await asyncio.gather(
            (self._history or recent)(session_id, text), self._recall(user_id)
        )
        run["memory"] = len(recall.items)
        if recall.dropped:
            run["memory_dropped"] = (
                recall.dropped
            )  # 记忆超过上限、按优先级没读的条数（spec [2026-10-23] §17）
        run["memory_ms"] = int((time.perf_counter() - read) * 1000)
        said["history"] = history
        reacting = asyncio.create_task(self._react(user_id, session_id, text, history))
        self._tasks.add(reacting)
        reacting.add_done_callback(self._tasks.discard)
        snap = asyncio.create_task(self._read_snapshot(user_id))
        train = asyncio.create_task(self._read_training(user_id, date.today()))
        wx = asyncio.create_task(self._read_weather(user_id))
        basics = asyncio.create_task(personal_basics(self._health_source(), user_id, session_id))
        files = await read_attachments(user_id, file_list, **self._files)
        if file_list:
            run["attachments"] = {"images": len(files.images), "reports": len(files.reports),
                                  "skipped": len(files.skipped)}  # fmt: skip
        try:
            async for block in self._answer_turn(
                user_id,
                session_id,
                text,
                history,
                recall,
                llm,
                run,
                said,
                prefix,
                snap,
                train,
                basics,
                files,
                wx,
            ):
                yield block
        finally:
            for task in (snap, train, basics, wx):
                task.cancel()

    async def _answer_turn(
        self,
        user_id: str,
        session_id: str,
        text: str,
        history: list[str],
        recall: Recall,
        llm: TurnLLM,
        run: dict[str, Any],
        said: dict[str, Any],
        prefix: str,
        snap: asyncio.Task[Snapshot],
        train: asyncio.Task[tuple[Plan | None, list[WorkoutLog], date | None]],
        basics: asyncio.Task[Personal],
        files: Attachments,
        wx: asyncio.Task[Weather | None] | None = None,
    ) -> AsyncGenerator[dict[str, Any]]:
        # 可能要追问、或者要被数据里的风险拦下的问题（问训练、排计划、回答追问）：先读完数据，用规则判断，
        # 需要追问或拦下时直接给固定的话，不调用模型（spec [2026-10-23] §5、§6）
        prep: Prepared | None = None
        training_ask = asks_training(text)
        if training_ask or PLAN_REQUEST.search(text) or asked(history) is not None:
            prep = await self._prepare(user_id, recall, text, history, snap, train, wx, run)
            stop = self._stop(prep, text, prefix, run, said, training=training_ask)
            if stop:
                yield text_block(stop)
                return
        if self._mode == "single":  # 单 Agent 对照组：一位全能教练一次作答，不调度、不整合
            r = Route(intent="pro", concerns=concerns_of(text), primary=Role.GENERAL, by="rule")
        else:
            d = await default_router().route(text, llm, history, recall.persona())
            r = as_route(d)
            run["route"] = d.log()  # 三路各自的得分与加权结果（不含原话）
            if files.images and (r.intent != "pro" or r.primary is None):
                r = keyword_route(text + "（附了图片）")  # 附了图片就当专业问题，按问题请人
            if (
                files.images and _FOOD.search(text) and Role.NUTRITION not in r.experts()
            ):  # 饭菜照片
                r = r.model_copy(update={"intent": "pro", "primary": Role.NUTRITION,
                                         "helpers": r.experts()[:MAX_HELPERS]})  # fmt: skip
            if r.intent == "pro" and r.primary is None:  # 三路都没打出分：按关键词兜底
                r = keyword_route(text)
            yield started("coach", "管家", "理解问题、安排专业角色")
            yield finished("coach", route_summary(r))
        run.update(intent=r.intent, route_by=r.by, concerns=list(r.concerns))
        if r.intent != "pro" or r.primary is None:
            run["path"] = "direct"
            answer = await direct(r.intent, text, history, llm, recall.persona())
            said["answer"] = answer
            yield text_block("\n\n".join(x for x in (prefix, answer) if x))
            return

        # 3. 共享档案（规则，不调用模型）：基本情况、限制、今天的身体状态、风险、指标计算、计划与记录
        if prep is None:
            prep = await self._prepare(user_id, recall, text, history, snap, train, wx, run)
        snapshot, plan, case, decision = prep.snapshot, prep.plan, prep.case, prep.decision
        run["snapshot_failed"] = snapshot.failed
        run["_missing"] = missing_readings(snapshot.readings)
        if snapshot.failed:
            yield notice("这次没读到你的健康数据，下面的回答没有用到它。")
        job = task_of(text)
        if job is None and decision.origin and task_of(decision.origin) == "plan":
            job = "plan"  # 回答"帮我做个训练计划"的追问（"你定吧"）：这一轮把计划排出来
        run["task"] = job
        needs_planner = decision.plan or job is not None
        if needs_planner and r.primary is not Role.GENERAL and Role.TRAINER not in r.experts():
            r = r.model_copy(update={"primary": Role.TRAINER, "helpers": r.experts()[:MAX_HELPERS]})
        roles = list(r.experts())
        training = decision.plan or (
            bool(set(roles) & TRAINING_ROLES)
            if r.primary is not Role.GENERAL
            else bool(_TRAINING.search(text))
        )
        stop = self._stop(prep, text, prefix, run, said, training=training)
        if stop:  # 调度后才看出是训练问题的，同样拦下
            yield text_block(stop)
            return
        seen = await (self._earlier or earlier)(session_id)  # 本会话之前的回答：说过的提醒不再重复
        notes = [x.note for x in case.risks if x.note not in seen]
        prefix = "\n\n".join(x for x in (prefix, files.note_for_user(), *notes) if x)

        # 4. 专业角色分层接力（§3）：评估 → 方案 → 动作细节；同一层同时作答、互不可见
        personal = await basics
        run["basics"] = len(personal.lines)
        run["roles"] = [x.value for x in roles]
        if recall.items:  # 记忆不在前端显示；用到哪几类只写进日志（只有类别，不含内容）
            used = sorted({x.category for x in recall.items})
            _log.info("ironm memory use %s", json.dumps({"turn": run["turn"], "categories": used}))
        index = {role: i for i, role in enumerate(roles)}
        # 问自己的数据（点到了指标）又没说哪里疼时，记忆里的伤病、今天的状态不再强制装伤痛和减量的规程
        # （限制照样写在共享档案里），免得问肌酐也装上"疼痛时怎么改动作"（spec [2026-10-23] §37）
        asks_data = bool(named_indicators(text)) and not _HURT.search(text)
        triggers = {name for name, on in (
            ("poor", (case.readiness.level in ("poor", "fair") or case.readiness.sick) and not asks_data),
            ("injury", bool(case.injuries) and not asks_data), ("plan", job == "plan"), ("log", job == "log"),
            ("image", bool(files.images)), ("move", bool(named_in(text))),
            *((k, True) for k in kinds_of(named_indicators(text))),
        ) if on}  # fmt: skip
        pictures = [x.part() for x in files.images]
        seeing = r.primary or roles[0]  # 图片只交给主责角色
        similar = default_router().similar  # 说法对不上时按语义选规程（spec [2026-10-23] §20）
        picked = {  # 路由选的规程加上系统情况要求的；路由没选的角色按规则选（§21）
            role: choose(role, text, triggers, similar, r.skills.get(role.value)) for role in roles
        }
        loaded = {role: got for role, (got, _) in picked.items()}
        run["skills_by"] = {role.value: by for role, (_, by) in picked.items()}
        tools_ctx = self._tool_context(user_id, snapshot, case, recall)
        run["skills"] = {role.value: [x.id for x in loaded[role]] for role in roles}
        checked, checked_note = await self._check_named(user_id, session_id, text, roles, run)
        results: dict[int, Consultation] = {}
        before: list[Consultation] = []
        solo = len(roles) == 1
        layers = layers_of(roles)
        run["layers"] = len(layers)
        for layer in layers:
            relay = relay_text(before)
            names = "、".join(spec_of(c.opinion.role).name for c in before if c.opinion.speak)
            tasks: dict[asyncio.Task[Consultation], int] = {}
            for role in layer:
                i, spec = index[role], spec_of(role)
                using = "、".join(x.name for x in loaded[role])
                yield started(
                    f"role-{i}",
                    spec.name,
                    spec.duty
                    + (f"（参考了{names}的结论）" if relay else "")
                    + (f"（规程：{using}）" if using else ""),
                )
                toolbox = Toolbox(
                    spec,
                    kb=self._kb,
                    health=self._health_source() if spec.health_data else None,
                    user_id=user_id,
                    session_id=session_id,
                    calcs=case.calcs,
                    context=tools_ctx,
                    meds=self._meds_source() if spec.health_data else None,
                    medical=self._medical_source(),
                )
                for c in before:
                    toolbox.evidence.absorb(c.evidence)
                if checked is not None:  # 规则先查到的数据：每位都能引用
                    toolbox.evidence.absorb(checked)
                lead = role in (Role.TRAINER, Role.GENERAL)
                note = "\n".join(x for x in (decision.note if lead else "",
                                              files.note_for_experts() if role is seeing else "", checked_note) if x)  # fmt: skip
                task = asyncio.create_task(
                    consult(
                        spec,
                        text,
                        history,
                        r.concerns,
                        toolbox,
                        llm,
                        personal,
                        recall,
                        solo=solo,
                        case=case,
                        relay=relay,
                        note=note,
                        task=job if lead else None,
                        today=snapshot.today,
                        skills=loaded[role],
                        images=pictures if role is seeing else (),
                    )
                )
                tasks[task] = i
            pending: set[asyncio.Task[Consultation]] = set(tasks)
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    i = tasks[task]
                    results[i] = task.result()
                    yield finished(
                        f"role-{i}",
                        consultation_summary(results[i]),
                        ok=results[i].status != "failed",
                    )
            before += [results[i] for i in tasks.values()]
        consultations = [results[i] for i in range(len(roles))]
        invited = [x.value for x in roles]
        run["_experts"] = [
            {"role": c.opinion.role.value, "status": c.status, **c.trace, "calls": c.evidence.calls,
             "mentions": mentioned_roles(c.opinion.body(), invited) if c.opinion.speak else []}
            for c in consultations
        ]  # fmt: skip
        run["statuses"] = [c.status for c in consultations]
        run["queries"] = sum(c.evidence.queries for c in consultations)
        run["pro_tools"] = sum(c.evidence.pro_queries for c in consultations)
        if any(c.evidence.health_failed for c in consultations):
            yield notice("这次没读到你的健康数据，下面的回答没有用到它。")

        # 5. 整合（只请到一位时由它直接作答），发出前核对数字、出处与内容约束（§4）
        if not any(c.opinion.speak for c in consultations):
            run["path"] = "no_answer"
            said["answer"] = ""  # 没能回答，也要记下用户这句话里说到的情况
            yield text_block("\n\n".join(x for x in (prefix, NO_ANSWER) if x))
            return
        ctx = Context.of(case)

        def rules(answer: str) -> list[Violation]:
            return check_constraints(answer, ctx)

        def mark(answer: str) -> str:
            return annotate(answer, ctx)

        primary = r.primary or roles[0]
        if solo:
            composed = await revise(
                consultations[0], text, llm, constraints=rules, memory=recall, annotate=mark
            )
        else:
            composed = await compose(text, primary, consultations, llm, recall,
                                     constraints=rules, annotate=mark, state=case.readiness.line())  # fmt: skip
        run.update(constraints=list(composed.violations), constraint_fixed=composed.fixed)
        run["_compose"] = {"checks": list(composed.checks), "repaired": composed.repaired,
                           "degraded": composed.degraded}  # fmt: skip
        writer = next(
            (c for c in consultations if c.opinion.role in (Role.TRAINER, Role.GENERAL)), None
        )
        cards = await self._preview(
            user_id, job, writer, text, plan, ctx, snapshot.today, run, llm, case, tools_ctx
        )
        if cards:
            note = CONFIRM_NOTE[job or "plan"]
            composed = replace(composed, text=composed.text.rstrip() + "\n\n" + note)
        blocks = self._answer(composed, prefix, run, said)
        tail = (
            2 if blocks[-1].get("tool_call_id") == SOURCES_ID else 0
        )  # 预览卡片放在“依据与来源”前面
        for block in [*blocks[: len(blocks) - tail], *cards, *blocks[len(blocks) - tail :]]:
            yield block

    async def _check_named(
        self, user_id: str, session_id: str, text: str, roles: Sequence[Role], run: dict[str, Any]
    ) -> tuple[Evidence | None, str]:
        """问题里点到具体指标时，作答前由规则先查这个人的这几项数据（spec [2026-10-23] §37）。
        运行记录里只记查了几项、查到几行，不记指标名。"""
        named = named_indicators(text)
        holder = next((spec_of(r) for r in roles if spec_of(r).health_data), None)
        if not named or holder is None:
            return None, ""
        pre = Toolbox(
            holder,
            kb=self._kb,
            health=self._health_source(),
            user_id=user_id,
            session_id=session_id,
        )
        try:
            found, rows, ok = await pre.prefetch_health(named)
        except Exception as e:  # 查不了不影响作答
            _log.warning("prefetch health failed: error_type=%s", type(e).__name__)
            found, rows, ok = "", 0, False
        run["prefetch"] = {"asked": len(named), "rows": rows, "ok": ok}
        return pre.evidence, checked_note(named, found, rows, ok)

    async def _preview(
        self,
        user_id: str,
        job: str | None,
        lead: Consultation | None,
        text: str,
        current: Plan | None,
        ctx: Context,
        today: date,
        run: dict[str, Any],
        llm: TurnLLM,
        case: CaseFile,
        tools: ToolContext | None = None,
    ) -> list[dict[str, Any]]:
        """训练教练写出的计划或记录：校验、按约束注明限制，存成预览（草稿），给出预览卡片（§9）。

        回答里没写出合格的计划或记录时，单独请训练教练补写一次（只要 JSON）。计划还要过计划检查
        （spec [2026-10-23] §12）：有问题时带着问题请训练教练改一次。
        """
        if job is None or lead is None or not lead.opinion.speak:
            return []
        try:
            raw = lead.opinion.plan if job == "plan" else lead.opinion.log
            ok = parse_plan(raw)[0] if job == "plan" else parse_log(raw, today)[0]
            if ok is None:
                current_json = (
                    json.dumps(current.model_dump(mode="json"), ensure_ascii=False)
                    if current
                    else ""
                )
                raw = await write_task(
                    llm, job, text, plain(lead.opinion.body()), case.text(), current_json
                )
                run["preview_retry"] = True
            if job == "plan":
                new, why = parse_plan(raw)
                if new is None:
                    run["preview"] = "invalid"
                    _log.info("preview invalid: kind=plan reason=%s", why)  # 只有字段位置，不含内容
                    return []
                new = annotate_plan(new, ctx)
                if tools is not None:
                    new, raw = await self._check_plan(
                        new, raw, text, lead, current, tools, ctx, llm, case, run
                    )
                changes = str((raw or {}).get("changes") or "")[:120]
                store = self._training_store()
                draft = await store.add_draft(user_id, "plan", plan_content(new, changes))
                run["preview"] = "plan"
                return plan_card(draft, new, current)
            log, why = parse_log(raw, today)
            if log is None:
                run["preview"] = "invalid"
                _log.info("preview invalid: kind=log reason=%s", why)
                return []
            log = trusted_log(log, text, current)
            draft = await self._training_store().add_draft(user_id, "log", log_content(log))
            run["preview"] = "log"
            return log_card(draft, log)
        except Exception as e:  # 存不了预览不影响回答
            _log.warning("preview failed: error_type=%s", type(e).__name__)
            run["preview"] = "failed"
            return []

    async def _check_plan(
        self,
        plan: Plan,
        raw: Any,
        text: str,
        lead: Consultation,
        current: Plan | None,
        tools: ToolContext,
        ctx: Context,
        llm: TurnLLM,
        case: CaseFile,
        run: dict[str, Any],
    ) -> tuple[Plan, Any]:
        """计划检查不过时，带着问题请训练教练改一次；改后问题更少才换上。日志只记结果，不记内容。"""

        limit = REVIEW_MAX_DAYS if text.startswith(REVIEW_ASK) else None

        def review(p: Plan) -> tuple[str, ...]:
            return check_plan(
                p,
                current=current,
                goal=tools.goal,
                injured=tools.injured,
                equipment=tools.equipment,
                max_changed_days=limit,
            ).problems

        problems = review(plan)
        run["plan_check"] = "pass" if not problems else "failed"
        if not problems:
            return plan, raw
        asked = (
            plain(lead.opinion.body())
            + "\n\n你写的计划没有通过检查，请按下面的问题改好，再完整写一遍：\n"
            + "\n".join(f"- {x}" for x in problems)
            + "\n\n你写的计划（JSON）："
            + json.dumps(plan.model_dump(mode="json"), ensure_ascii=False)
        )
        current_json = (
            json.dumps(current.model_dump(mode="json"), ensure_ascii=False) if current else ""
        )
        fix = await write_task(llm, "plan", text, asked, case.text(), current_json)
        fixed = parse_plan(fix)[0]
        if fixed is None:
            return plan, raw
        fixed = annotate_plan(fixed, ctx)
        left = review(fixed)
        if len(left) >= len(problems):
            return plan, raw
        run["plan_check"] = "fixed" if not left else "partly"
        return fixed, fix

    async def _prepare(
        self,
        user_id: str,
        recall: Recall,
        text: str,
        history: list[str],
        snap: asyncio.Task[Snapshot],
        train: asyncio.Task[tuple[Plan | None, list[WorkoutLog], date | None]],
        wx: asyncio.Task[Weather | None] | None = None,
        run: dict[str, Any] | None = None,
    ) -> Prepared:
        """共享档案与要不要追问（都是规则，不调用模型）。数据、计划和天气在这一轮开始时就同时在读了。"""
        snapshot, (plan, logs, since) = await snap, await train
        lines = case_lines(plan, logs, snapshot.today, since)
        case = build_case(
            snapshot, recall, text, plan=lines + target_lines(plan, logs, snapshot.today)
        )
        current = await wx if wx is not None else None
        if current is not None:
            case = replace(case, weather=_weather_case(current, plan, snapshot.today))
        if run is not None:
            run["weather"] = current is not None
        decision = decide(text, history, recall, snapshot.profile, has_plan=plan is not None)
        return Prepared(snapshot, plan, case, decision)

    def _stop(
        self,
        prep: Prepared,
        text: str,
        prefix: str,
        run: dict[str, Any],
        said: dict[str, Any],
        *,
        training: bool,
    ) -> str:
        """要拦下（数据里的风险）或先追问时，返回给用户的固定的话；否则返回空。"""
        case, decision = prep.case, prep.decision
        run.update(readiness=case.readiness.level, risks=[x.key for x in case.risks])
        blocked = next((x for x in case.risks if x.block), None)
        if blocked is not None and (training or decision.plan):  # §5：这一轮不给训练安排
            run["path"] = "risk"
            said["answer"] = ""
            return "\n\n".join(x for x in (prefix, blocked.note, RISK_BLOCK) if x)
        if decision.ask:  # §6：信息不够先追问
            run.update(path="clarify", missing=list(decision.missing))
            said["answer"] = decision.ask
            return "\n\n".join(x for x in (prefix, decision.ask) if x)
        return ""

    def _answer(
        self, composed: Composed, prefix: str, run: dict[str, Any], said: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """回答正文与可展开的“依据与来源”。"""
        run.update(path="answer", degraded=composed.degraded, rewrites=composed.rewrites,
                   kb=[e.id for e in composed.entries])  # fmt: skip
        blocks = []
        if composed.degraded:
            blocks.append(notice("这次回答受限：整合没有通过核对，下面给出主责角色核对过的意见。"))
        said["answer"] = answer_text(composed)
        blocks.append(text_block(answer_text(composed, prefix=prefix)))
        sources = sources_text(composed)
        if sources:  # 出处不写进正文，放进可展开的“依据与来源”
            blocks.append(started(SOURCES_ID, SOURCES_NAME, "这条回答用到的资料、计算和你的数据"))
            blocks.append(finished(SOURCES_ID, sources))
        return blocks
