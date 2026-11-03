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
from collections.abc import AsyncGenerator, Awaitable, Callable, Coroutine, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from functools import cache, partial
from typing import Any, Literal

from ironm_agent.actions import LOG_WORKOUT, NEW_PLAN, PLAN_EDIT, Desk, Handler, Outcome
from ironm_agent.agent import EXTRA_TOOLS, respond
from ironm_agent.attachments import Attachments
from ironm_agent.attachments import read as read_attachments
from ironm_agent.casefile import CaseFile, Snapshot
from ironm_agent.casefile import build as build_case
from ironm_agent.checks import plain
from ironm_agent.clarify import (
    CONFIRMED_NOTE,
    HEAD,
    PLAN_REQUEST,
    Decision,
    asked,
    conditions,
    confirm_ask,
    decide,
    replies,
    wants_new,
)
from ironm_agent.compose import Composed, revise
from ironm_agent.constraints import Context, Violation, annotate, annotate_plan
from ironm_agent.constraints import check as check_constraints
from ironm_agent.day_state import DayState, DayStore, default_day
from ironm_agent.day_state import lines as day_lines
from ironm_agent.day_state import note as note_day
from ironm_agent.day_state import signals as day_signals
from ironm_agent.exercises import named_in
from ironm_agent.goal import GoalStore, default_goal
from ironm_agent.goal import line as target_line
from ironm_agent.harness import TraceStore, missing_readings, new_turn, react
from ironm_agent.illness import (
    Episode,
    IllnessStore,
    default_illness,
    detect,
    due,
    mentions,
    merge,
    question,
    recovering_days,
    reply_of,
    state_line,
    today_mode,
)
from ironm_agent.illness import active as active_illness
from ironm_agent.illness import answer as answer_illness
from ironm_agent.illness import (
    recent as recent_illness,
)
from ironm_agent.illness import summary_line as illness_line
from ironm_agent.indicators import named_indicators, record_kinds
from ironm_agent.kb import KnowledgeBase, default_kb
from ironm_agent.llm import ModelsConfig, TurnLLM, load_models
from ironm_agent.memory import USER, earlier, last_sources, recent, split_thread, user_lines, whole
from ironm_agent.memory_extract import (
    changes_of,
    extract,
    validate,
)
from ironm_agent.memory_layers import (
    PAIN_DAYS,
    RECALL,
    RECALL_SCHEMA,
    daily_asks,
    layers,
    recall_tool,
)
from ironm_agent.memory_prefs import due as prefs_due
from ironm_agent.memory_prefs import refresh as refresh_prefs
from ironm_agent.memory_store import Item, MemoryStore, default_store
from ironm_agent.memory_view import Recall
from ironm_agent.metrics import GOALS
from ironm_agent.personal import Personal, personal_basics
from ironm_agent.plan_ops import (
    SCOPE_HINT,
    Conflict,
    Op,
    apply,
    blocked_days,
    describe,
    fit_time,
    meant,
    parse_ops,
    scope_hint,
)
from ironm_agent.progression import target_lines
from ironm_agent.protools.plan_check import check_plan, same_training
from ironm_agent.protools.registry import ToolContext
from ironm_agent.provenance import is_provenance, provenance_note
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
from ironm_agent.roles import COACH_NAME, GENERAL, Role, spec_of
from ironm_agent.router import concerns_of
from ironm_agent.safety.emergency import assess
from ironm_agent.safety.refusals import KINDS as REFUSAL_KINDS
from ironm_agent.safety.refusals import default_refusals
from ironm_agent.safety.replies import (
    REPLIES_PATH,
    Replies,
    four_section,
    load_replies,
    refusal_sections,
)
from ironm_agent.session_summary import SHOW, Summary, SummaryStore, default_summaries, summarize
from ironm_agent.session_summary import due as summary_due
from ironm_agent.skill_route import route as route_skills
from ironm_agent.skills import pick_any, pick_routed
from ironm_agent.special import flags as special_flags
from ironm_agent.special import is_special
from ironm_agent.special import rules_text as special_rules
from ironm_agent.spoken import HELP, REFUSAL_NEEDS, RISK_NEEDS, URGENT, missing, say, urgent_needs
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
    schedule_line,
    task_of,
    trusted_log,
    weekday_name,
)
from ironm_agent.triggers import PainStore, default_pain, pain_parts
from ironm_agent.weather import Weather
from ironm_agent.weather import case_line as weather_line
from ironm_agent.weather import for_user as weather_for

_log = logging.getLogger("ironm_agent.run")
_DAILY: dict[str, date] = {}  # 每个人今天查过"该问的"没有（§73，同一进程内）
SYNC_WAIT_S = 20  # 作答前最多等上一轮的档案与记忆更新多少秒（spec [2026-10-23] §51）

FAILED = "IronM 这次没能回答，请稍后再试。"
CONFLICT_ASK = (
    "我没法确定你想怎么改。请分开说：先说一条，确认后再说下一条。"  # 改计划的要求互相矛盾时（§45）
)
REVIEW_ASK = "按这周的复盘调整训练计划"  # 每周复盘一键生成调整方案时的问法（spec [2026-10-23] §18）
REVIEW_MAX_DAYS = 2  # 按复盘调整每次最多改几天
SCOPES = ("once", "always", "unclear")  # 改计划只改这次、以后都这样、没说清（§114）
WEATHER_WAIT_S = 4.0  # 天气最多等 4 秒（同一个地方 10 分钟内有缓存）
NO_TEXT = "没有收到文字问题。"
NO_ANSWER = "抱歉，这次没答上来，过一会儿再问我一次吧。"
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


def default_coach_store() -> Any:
    """管家方案的存储，用线上的（测试里换掉）。"""
    from ironm_agent.web_more import coach_deps

    return coach_deps().store


async def default_coach_eval(user_id: str, reason: str, force: bool) -> None:
    """管家重新评估当前方案，用线上的存储（测试里换掉）。"""
    from ironm_agent.coach_state import evaluate
    from ironm_agent.web_more import coach_deps

    deps = coach_deps()
    await evaluate(user_id, deps, reason=reason, force=force)
    if not force:  # 每天第一次提问：后台跑一次管家复盘，由模型决定调不调（§85）
        from ironm_agent.review import daily_later

        daily_later(user_id, deps)


RISK_BLOCK = "这一轮先不给训练安排。饮食、睡眠或者你的数据，可以照常问我。"
CONFIRM_NOTE = {
    "plan": "下面是计划预览，点「确认」才会保存，保存后也能撤销。",
    "log": "下面是这次训练的记录预览，点「确认」才会记下。",
}
# 本会话里这些回答给全文、不压成要点（列给他确认的条件、给出过的预览，spec [2026-10-23] §68）
KEEP_WHOLE = (HEAD, *CONFIRM_NOTE.values())
# 上一轮刚给了计划预览：这句先当成对预览的回应（"都不好"曾被当成对更早那张确认条件清单的回答，10-29 重放）
PREVIEWED_NOTE = (
    "上一轮你刚给了计划预览（要点见上面的现在的情况）。他这句如果是在回应这份预览（说好不好、补条件、要改哪里）："
    "说不行、不好、不喜欢时，复述预览要点，问是哪里不行（动作、天数、时长、强度），不要回到排计划前的确认条件；"
    "他问的是别的事，就只答他问的，不提这份预览、不写计划（§108）。"
)
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


# "尿酸""乳酸""叶酸""氨基酸"里的"酸"不是酸痛（spec [2026-10-23] §39）
_HURT = re.compile(r"疼|痛|伤|肿|麻|(?<![尿乳叶基胃])酸(?!奶)|不舒服|难受")
_BETTER_WORDS: dict[str, Any] = {"好了": "resolved", "好些": "better", "没好": "unwell"}


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


_WEEKDAY = re.compile(r"(?:周|星期|礼拜)[一二三四五六日天]")


def _no_day(problem: str) -> str:
    """去掉星期几再比较：挪了天的同一个老问题不算新问题。"""
    return _WEEKDAY.sub("", problem)


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
        observe: Callable[[dict[str, Any]], None] | None = None,
        weather: Callable[[str], Awaitable[Weather | None]] | None = None,
        pain: PainStore | None = None,
        illness: IllnessStore | None = None,
        day: DayStore | None = None,
        medications: Any | None = None,
        medical: Any | None = None,
        traces: TraceStore | None = None,
        goals: GoalStore | None = None,
        summaries: SummaryStore | None = None,
        **kwargs: Any,
    ) -> None:
        self._summaries = (
            summaries  # 会话摘要（spec [2026-10-23] §73，默认用数据库里 iron-m 自己的表）
        )
        self._traces = (
            traces  # 运行框架的轨迹（spec [2026-10-23] §31，默认用数据库里 iron-m 自己的表）
        )
        # mirobody 的用药记录与医学知识（spec [2026-10-23] §25）；测试时换成假的，注入了 health 却没给的不用
        self._meds = medications
        self._medical = medical
        self._pain = pain  # 说疼的部位和日期（触发型调整用，默认用数据库里 iron-m 自己的表）
        self._illness = illness  # 生病记录（spec [2026-10-23] §46，默认用数据库里 iron-m 自己的表）
        self._coach_store: Any = None  # 管家的方案（§84 读"不用这样调"；None 用线上的，测试里换掉）
        self._coach_cache: dict[str, tuple[date, Any]] = {}  # 同一轮只读一次管家方案（§97）
        self._web_search: Any = None  # 联网搜索（§91）；None 时按环境变量里的密钥配，测试里换成假的
        self._web_log: Any = None  # 联网查询的待审清单；None 用数据库里的
        self._goals = goals  # 目标体重和日期（排新计划前追问时带上，spec [2026-10-23] §55）
        self._day = day  # 今日状态（spec [2026-10-23] §54，默认用数据库里 iron-m 自己的表）
        self._weather = weather  # 这个人所在城市的天气（默认按"我的"里设置的城市去取）
        self._snapshot = snapshot  # 这个人的档案、健康数据与指标（默认与数据页同一份计算）
        self._files: dict[str, Any] = dict(files or {})  # 读附件的方式（测试时换成假的）
        self._memory = memory  # 长期记忆（默认用数据库里 iron-m 自己的表）
        self._training = training  # 训练计划、训练记录与预览（默认用数据库里 iron-m 自己的表）
        # 以下几项给考题用：本会话前几轮、上一条回答的来源（默认读 mirobody 的对话记录）、
        # 回答后是否提取记忆、每轮结束时拿到运行记录
        self._history = history
        self._transcript: Callable[[str], Awaitable[list[str]]] | None = (
            None  # 测试时换掉读整个会话
        )
        self._earlier = earlier
        self._sources = sources
        self._remember_on = remember
        self._observe = observe
        self._locks: dict[str, asyncio.Lock] = {}  # 同一个人的记忆提取一次只跑一个
        self._tasks: set[asyncio.Task[None]] = set()  # 后台提取记忆的任务
        # 每个人还没写完的档案与记忆更新：下一轮作答前先等它们做完（spec [2026-10-23] §51）
        self._pending: dict[str, set[asyncio.Task[None]]] = {}
        self._sync_wait = SYNC_WAIT_S
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
        self,
        user_id: str,
        snapshot: Snapshot,
        case: CaseFile,
        recall: Recall,
        found: Sequence[Any] | None = None,
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
            age=snapshot.profile.age(snapshot.today),
            profile=snapshot.profile,
            found=found,  # 这一轮已经认出的情况（§84），和档案里的指标解读一致
            special=special_flags(snapshot.profile, case.risks, snapshot.today),  # §95
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

    def _summary_store(self) -> SummaryStore:
        if self._summaries is None:
            self._summaries = default_summaries()
        return self._summaries

    async def _memory_items(self, user_id: str) -> list[Item]:
        """这个人的全部记忆（含被取代、已结束的），四层记忆和查记忆工具用；读不到时当作没有。"""
        try:
            return await self._memory_store().items(user_id, current_only=False)
        except Exception as e:
            _log.warning("memory unavailable: error_type=%s", type(e).__name__)
            return []

    async def _daily_memory(self, user_id: str, today: date, run: dict[str, Any]) -> None:
        """每天第一次聊天前查一次（§73 需求 7、9，只用规则）：反复说疼、练得远少于计划 → 生成该问的。"""
        if _DAILY.get(user_id) == today:
            return
        _DAILY[user_id] = today
        try:
            store = self._memory_store()
            if await store.paused(user_id):
                return
            items = await store.items(user_id, current_only=False)
            pains = await self._pain_store().since(user_id, today - timedelta(days=PAIN_DAYS))
            training = self._training_store()
            plan = await training.plan(user_id)
            logs = await training.workouts(user_id, today - timedelta(days=28))
            asks = daily_asks(
                items, pains, plan.plan if plan else None, [x.log for x in logs], today
            )
            if asks:
                await store.apply(user_id, asks)
            run["memory_daily"] = len(asks)
        except Exception as e:  # 查不了不影响回答
            _log.warning("daily memory check failed: error_type=%s", type(e).__name__)

    async def _summarize(self, user_id: str, session_id: str, turns: int) -> None:
        """会话摘要（§73 需求 4、6）：3 句以上写第一次，之后每多 4 句更新；答应的事记成待跟进。日志只记条数。"""
        start = time.perf_counter()
        try:
            store = self._summary_store()
            if not summary_due(await store.get(user_id, session_id), turns):
                return
            memory = self._memory_store()
            if await memory.paused(user_id):
                return
            lines = await (self._transcript or whole)(session_id)
            if not lines:
                return
            items = await memory.items(user_id)
            llm = TurnLLM(self._models, self._environ)
            text, follow = await summarize(llm, lines, date.today(), items)
            if not text:
                return
            await store.put(user_id, Summary(session_id, text, turns, datetime.now().astimezone()))
            if follow:
                await memory.apply(user_id, follow)
        except Exception as e:  # 写不了不影响已经发出的回答
            _log.warning("session summary failed: error_type=%s", type(e).__name__)
            return
        _log.info("ironm summary %s", json.dumps({"turns": turns, "followups": len(follow),
                                                   "ms": int((time.perf_counter() - start) * 1000)}))  # fmt: skip

    def _illness_store(self) -> IllnessStore:
        if self._illness is None:
            self._illness = default_illness()
        return self._illness

    def _goal_store(self) -> GoalStore:
        if self._goals is None:
            self._goals = default_goal()
        return self._goals

    async def _target(self, user_id: str, snapshot: Snapshot) -> str:
        """目标体重和日期的一句话（排新计划前确认时带上，spec [2026-10-23] §55 需求 2）；读不到时当作没有。"""
        try:
            g = await self._goal_store().get(user_id)
        except Exception as e:  # 读不到目标不影响作答
            _log.warning("goal read failed: error_type=%s", type(e).__name__)
            return ""
        return target_line(g, snapshot) if g is not None else ""

    def _day_store(self) -> DayStore:
        if self._day is None:
            self._day = default_day()
        return self._day

    async def _read_day(self, user_id: str, run: dict[str, Any]) -> DayState | None:
        """今天的状态（只读）；读不到当作没有。"""
        run["_at"] = datetime.now(UTC)
        try:
            return await self._day_store().get(user_id, date.today())
        except Exception as e:
            _log.warning("day state unavailable: error_type=%s", type(e).__name__)
            return None

    async def _settle_state(self, user_id: str, text: str, run: dict[str, Any]) -> None:
        """作答后写他这句说了自己什么（§114）：管家这一轮作答了就按它给的 said（没给就是没说），
        管家失败或走了别的路才按关键词兜底。由谁判断在作答结束时就记进运行记录（state_by）。"""
        if run.get("state_by") == "model":
            await self._apply_said(user_id, run.get("_said_state") or {}, run)
            return
        await self._track_illness(user_id, text, run)
        await self._note_day(user_id, text, run)
        if parts := pain_parts(text):
            run["pain_parts"] = len(parts)
            await self._record_pain(user_id, parts)

    async def _apply_said(self, user_id: str, told: Mapping[str, Any], run: dict[str, Any]) -> None:
        """管家判断的他这句说了自己什么：写生病记录、今日状态、疼痛记录（字段不对的跳过）。"""
        from ironm_agent.casefile import PARTS
        from ironm_agent.day_state import Entry

        today, at = date.today(), run.get("_at") or datetime.now(UTC)
        sick = str(told.get("sick") or "").strip()[:20]
        better = _BETTER_WORDS.get(str(told.get("better") or "").strip())
        if sick or better:
            try:
                store = self._illness_store()
                eps = await recent_illness(store, user_id, today)
                now = active_illness(eps, today)
                changed: Episode | None = None
                if better is not None and now:
                    changed, _ = answer_illness(now[0], better, today)
                elif sick:  # 管家写的症状归到哪一类（只是给它的话归类）
                    found = detect(sick) or (["身体不适"], "vague")
                    changed = merge(eps, found[0], found[1], today)
                if changed is not None:
                    await store.save(user_id, changed)
                    run["illness"] = f"said:{changed.status}"
            except Exception as e:
                _log.warning("illness save failed: error_type=%s", type(e).__name__)
        entries: list[Any] = []
        if told.get("tired") is True:
            entries.append(Entry(kind="tired", at=at))
        sleep = told.get("sleep")
        if isinstance(sleep, int | float) and not isinstance(sleep, bool) and 0 <= sleep <= 16:
            entries.append(Entry(kind="sleep", at=at, hours=float(sleep) or None))
        minutes = told.get("minutes")
        if isinstance(minutes, int) and not isinstance(minutes, bool) and 5 <= minutes <= 240:
            entries.append(Entry(kind="minutes", at=at, minutes=minutes))
        if told.get("good") is True:
            entries.append(Entry(kind="good", at=at))
        if entries:
            try:
                await self._day_store().add(user_id, today, entries)
                run["day_noted"] = len(entries)
                await self._coach(user_id, "说了今天的状态", True)  # 首页今天的版本跟着变
            except Exception as e:
                _log.warning("day state save failed: error_type=%s", type(e).__name__)
        pain = told.get("pain")
        words = [str(x) for x in pain] if isinstance(pain, list) else []
        if parts := [k for k, p in PARTS.items() if any(p.search(w) for w in words)]:
            run["pain_parts"] = len(parts)
            await self._record_pain(user_id, parts)

    async def _note_day(self, user_id: str, text: str, run: dict[str, Any]) -> DayState | None:
        """这句话里说到今天的状态（累、没睡好、只有多少分钟）：作答前写进今日状态（规则，spec [2026-10-23] §54）。"""
        at = datetime.now(UTC)
        run["_at"] = at
        state, new = await note_day(self._day_store(), user_id, text, at)
        if new:
            run["day_noted"] = len(new)  # 只记条数，不记内容
            self._later(
                user_id, self._coach(user_id, "说了今天的状态", True)
            )  # 首页今天的版本跟着变
        return state

    async def _coach_state(self, user_id: str) -> Any:
        """管家的当前方案（读不到当作没有）；同一轮读一次，每轮开始时清掉。"""
        cached = self._coach_cache.get(user_id)
        if cached is not None and cached[0] == date.today():
            return cached[1]
        try:
            state = await (self._coach_store or default_coach_store()).get(user_id)
        except Exception as e:
            _log.info("coach state unavailable: error_type=%s", type(e).__name__)
            state = None
        self._coach_cache[user_id] = (date.today(), state)
        return state

    async def _today_lines(
        self,
        user_id: str,
        plan: Plan | None,
        today: date,
        state: DayState | None,
        ill: list[Episode],
    ) -> list[str]:
        """共享档案第一段"今天"：计划、打卡（带时间）、今天说过的状态、生病、最近说疼的部位，
        以及"今天的版本"（和首页、管家消息同一份，§97）。"""
        session = plan.session_on(today) if plan is not None else None
        checkins: list[Any] = []
        pains: list[tuple[str, date]] = []
        try:
            checkins = await self._training_store().workouts(user_id, today)
        except Exception as e:
            _log.warning("checkins unavailable: error_type=%s", type(e).__name__)
        try:
            pains = await self._pain_store().since(user_id, today - timedelta(days=3))
        except Exception as e:
            _log.warning("pain unavailable: error_type=%s", type(e).__name__)
        from ironm_agent.protools.movement import JOINT_NAMES

        named = [(JOINT_NAMES.get(p, p), d) for p, d in pains]
        out = day_lines(state, today=today, plan_name=session.name if session else None,
                        checkins=checkins, illness=illness_line(ill, today), pains=named)  # fmt: skip
        coach = await self._coach_state(user_id)
        item = coach.item("today") if coach is not None and coach.day == today else None
        if item is not None:
            out.append(
                f"今天的版本（和首页、管家消息一致）：{item.title}"
                + (f"（{item.why}）" if item.why else "")
            )
        return out

    async def _track_illness(self, user_id: str, text: str, run: dict[str, Any]) -> list[Episode]:
        """这句话里说生病了、或在回答"好了没"：更新生病记录（规则，不调用模型；spec [2026-10-23] §46）。
        返回更新后的记录；读写失败时当作没有记录。日志只记级别和状态。"""
        store, today = self._illness_store(), date.today()
        eps = await recent_illness(store, user_id, today)
        now = active_illness(eps, today)
        reply = reply_of(text) if now else None
        found = detect(text)
        changed: Episode | None = None
        if now and reply is not None:
            changed, _ = answer_illness(now[0], reply, today)
            run["illness"] = f"answered:{reply}"
        elif found is not None:
            changed = merge(eps, found[0], found[1], today)
            run["illness"] = f"noted:{changed.level}"
        if changed is not None:
            try:
                await store.save(user_id, changed)
            except Exception as e:
                _log.warning("illness save failed: error_type=%s", type(e).__name__)
            eps = [changed if e.id == changed.id else e for e in eps]
            if all(e.id != changed.id for e in eps):
                eps.append(changed)
        return eps

    async def _illness_followup(self, user_id: str, run: dict[str, Any]) -> str:
        """今天还没问过、也还没回答的生病：返回追问的一句，并记下今天问过了。"""
        today = date.today()
        if str(run.get("illness", "")).startswith("answered"):
            return ""
        for ep in active_illness(run.get("_ill") or [], today):
            if due(ep, today) and ep.asked != today:
                try:
                    await self._illness_store().save(
                        user_id, ep.model_copy(update={"asked": today})
                    )
                except Exception as e:
                    _log.warning("illness save failed: error_type=%s", type(e).__name__)
                    return ""
                run["illness_asked"] = True
                return question(ep, today)
        return ""

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
            await self._illness_from_memory(user_id, out.changes)
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

    async def _remember_now(
        self,
        user_id: str,
        text: str,
        answer: str,
        ops: list[dict[str, Any]],
        known: Mapping[str, Any],
        run: dict[str, Any],
        today: date,
    ) -> bool:
        """单 Agent 在回答里写的记忆：按提取的规则核对后当场写入（spec [2026-10-23] §68）。
        返回是否给出过记忆（写了就不再后台提取）；运行记录只记条数，不记内容。"""
        checked, rejected = validate({"ops": ops}, known, text, answer, today=today)
        run["memory_now"] = len(checked)
        if rejected:
            run["memory_now_rejected"] = len(rejected)
        if not checked:
            return False
        store = self._memory_store()
        try:
            async with self._locks.setdefault(user_id, asyncio.Lock()):
                if await store.paused(user_id):
                    return True
                changes = changes_of(checked)
                await store.apply(user_id, changes)
            # 生病记录由管家的 said 写（§114），这里不再按记下的内容另开一次；后台兜底提取那条路照旧
        except Exception as e:  # 记不下来不影响回答，后台提取兜底
            _log.warning("memory write failed: error_type=%s", type(e).__name__)
            return False
        return True

    async def _illness_from_memory(self, user_id: str, changes: Sequence[Any]) -> None:
        """词表认不出、后台提取记忆的模型记成身体不适的，也记成一次生病；模型记下"已经好了"的，
        结束正在进行的那次（spec [2026-10-23] §46）。"""
        events = [c.item.content for c in changes if c.kind == "insert" and c.item is not None
                  and c.item.category in ("event", "injury")]  # fmt: skip
        if not events:
            return
        store, today = self._illness_store(), date.today()
        eps = await recent_illness(store, user_id, today)
        now = active_illness(eps, today)
        for text in events:
            reply = reply_of(text) if now else None
            found = detect(text)
            if now and reply is not None:
                changed, _ = answer_illness(now[0], reply, today)
            elif found is not None and not now:
                changed = merge(eps, found[0], found[1], today)
            else:
                continue
            try:
                await store.save(user_id, changed)
            except Exception as e:  # 记不了不影响已经发出的回答
                _log.warning("illness save failed: error_type=%s", type(e).__name__)
            return

    async def _refresh_prefs(self, user_id: str) -> None:
        try:
            await refresh_prefs(user_id, self._memory_store(), self._training_store())
        except Exception as e:  # 出错不影响已经发出的回答
            _log.warning("prefs refresh failed: error_type=%s", type(e).__name__)

    def _later(self, user_id: str, work: Coroutine[Any, Any, None]) -> None:
        """在后台更新这个人的档案或记忆；下一轮作答前会先等它做完。"""
        task = asyncio.create_task(work)
        pending = self._pending.setdefault(user_id, set())
        for group in (self._tasks, pending):
            group.add(task)
            task.add_done_callback(group.discard)

    async def _sync(self, user_id: str, run: dict[str, Any]) -> None:
        """等这个人上一轮还没写完的更新，最多等 _sync_wait 秒；没等完照常作答（spec [2026-10-23] §51）。"""
        pending = [t for t in self._pending.get(user_id, ()) if not t.done()]
        if not pending:
            return
        start = time.perf_counter()
        _, left = await asyncio.wait(pending, timeout=self._sync_wait)
        run["sync_ms"] = int((time.perf_counter() - start) * 1000)
        if left:
            run["sync_timeout"] = len(left)

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

    def _timeline_tool(self, user_id: str, raw: Sequence[Any], today: date) -> dict[str, Any]:
        """时间线（§97）：生病、伤病和近期的事、说疼、训练、管家的调整按日期排在一起，只读。"""
        from ironm_agent import timeline

        async def workouts(start: date) -> list[WorkoutLog]:
            return [x.log for x in await self._training_store().workouts(user_id, start)]

        async def changes() -> list[Any]:
            return list(await (self._coach_store or default_coach_store()).history(user_id, 200))

        run = timeline.tool(today, illness=lambda s: self._illness_store().since(user_id, s),
                            memory=raw, pains=lambda s: self._pain_store().since(user_id, s),
                            workouts=workouts, changes=changes)  # fmt: skip
        return {timeline.SCHEMA["function"]["name"]: (timeline.SCHEMA, run)}

    def _web_tools(self, today: date) -> dict[str, Any]:
        """联网搜索（§91）：配了密钥才给管家；查询词和网址记进待审清单。"""
        from ironm_agent.web_search import SCHEMA, configured, default_log, web_tool

        search = self._web_search or configured(self._environ)
        if search is None:
            return {}
        log = self._web_log if self._web_log is not None else default_log()
        return {SCHEMA["function"]["name"]: (SCHEMA, web_tool(search, log, today))}

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
        run: dict[str, Any] = {"turn": uuid.uuid4().hex[:12], "path": "error", "agent": "single"}
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
            run["state_by"] = "model" if run.get("_judged_state") else "keyword"
            self._later(user_id, self._settle_state(user_id, text, run))  # 他说了自己什么（§114）
            if "answer" in said and self._remember_on:
                if said.get("remembered"):  # 单 Agent 这一轮已经当场记了（§68）
                    run["memory_extract"] = "agent"
                else:  # 不先用关键词判断，后台兜底提取一次（§68）
                    self._later(
                        user_id,
                        self._remember(user_id, text, said["answer"], user_lines(said["history"])),
                    )
                # 每天第一次提问时管家评估一次（今天评估过就不再算）
                self._later(user_id, self._coach(user_id, "每天第一次提问", False))
                # 会话摘要（§73）：到了该写的时候才调模型
                turns = sum(1 for x in said["history"] if x.startswith(USER)) + 1
                self._later(user_id, self._summarize(user_id, session_id, turns))
                if prefs_due(user_id):  # 每天第一次回答之后，后台更新训练记录得出的偏好
                    self._later(user_id, self._refresh_prefs(user_id))
        except Exception as e:  # 不把异常原文给用户
            _log.error("turn failed: error_type=%s", type(e).__name__)
            run["error_type"] = type(e).__name__
            yield {"type": "error", "message": FAILED}
        finally:
            # 这一轮存下、卡片却没发出去的预览（出错、断开、被取消）作废（§120）；放进后台，取消时也能跑完
            if (desk := run.pop("_desk", None)) is not None and desk.drafts:
                self._later(user_id, self._drop_drafts(user_id, desk.drafts))
            run["ms"] = int((time.perf_counter() - start) * 1000)
            run["model_calls"] = len(llm.calls)
            run["model_failures"] = sum(1 for c in llm.calls if not c.ok)
            run["budget_hit"] = len(llm.calls) >= self._models.turn_budget
            # 耗时放在前面：mirobody 会截断过长的日志行；各环节明细（_ 开头）只进轨迹，不进日志
            first = (
                "turn",
                "path",
                "action",
                "actions",  # 动作工具：只有工具名和结果类别（§120），放前面免得被截断
                "agent",
                "ms",
                "memory",
                "memory_ms",
                "model_calls",
                "model_failures",
            )
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
        # 1. 安全前置：判定只用规则。急症与红旗交给模型说，代码查必须说到的几点（停下、120 或就医、
        #    不给训练安排），没说到或模型失败时退回四段式固定回答（spec [2026-10-23] §86）；不读数据、不调工具
        self._coach_cache.pop(user_id, None)  # 管家方案每轮重新读一次（§97）
        assessment = assess(text)
        refusals = default_refusals().detect(text)
        replies = _replies()
        run["safety"] = assessment.level
        run["refusals"] = list(refusals.kinds)
        if assessment.level != "none":
            run["path"] = "safety"
            sections = four_section(replies, assessment) + refusal_sections(replies, refusals.kinds)
            spoken = await say(
                llm, URGENT, "\n".join(f"{x.title}：{x.text}" for x in sections), text,
                urgent_needs(assessment.level, assessment.categories),
            )  # fmt: skip
            run["safety_by"] = "model" if spoken else "fixed"
            yield text_block(spoken or sections_text(sections))
            return
        # 拒答：交给模型说（没提医生时再补固定的一句，§86）
        prefix = "".join(replies.refusals[k] for k in refusals.kinds)
        run["_refused"] = prefix

        asker, _ = split_thread(session_id)
        if asker and asker != user_id:  # 关爱圈里替别人问：只说明不支持（不读对方数据，§86）
            run["path"] = "help_ask"
            spoken = await say(llm, HELP, "", text)
            run["help_by"] = "model" if spoken else "fixed"
            yield text_block(spoken or HELP_ASK)
            return

        # 2. 读本会话前几轮与这个人的记忆（全部有效记忆，不靠检索）；同时开始读他的数据（档案、健康数据、
        #    指标），与路由并行（spec [2026-10-23] §7）
        await self._sync(user_id, run)  # 先等上一轮的档案和记忆写完再读（spec [2026-10-23] §51）
        await self._daily_memory(user_id, date.today(), run)
        read = time.perf_counter()
        history, recall, ill, day = await asyncio.gather(
            (self._history or partial(recent, keep=KEEP_WHOLE))(
                session_id, text
            ),  # 确认条件、卡片说明完整保留（§68）
            self._recall(user_id),
            # 生病记录、今日状态作答前只读（§114）：他这句说了什么由管家判断，作答后再写；管家失败才按关键词
            recent_illness(self._illness_store(), user_id, date.today()),
            self._read_day(user_id, run),
        )
        run["_day"] = day
        if not active_illness(ill, date.today()):
            # 没有正在进行的生病：跟生病有关的近期事件和建议不再交给角色（spec [2026-10-23] §46）
            recall = recall.without(
                lambda x: x.category in ("event", "advice") and mentions(x.content)
            )
        run["_ill"] = ill
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
            async for block in self._single_turn(
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

    async def _single_turn(
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
        """单 Agent 一轮（spec [2026-10-23] §67）：不路由、不整合；Skill 跨领域按需装、工具按需调；
        改计划、排新计划、记训练由它在回答里给出，系统执行。数据风险、拒答由规则判定，话由它说，
        代码查必须说到的几点，没说到才退回固定回答（§86）。"""
        prep = await self._prepare(user_id, recall, text, history, snap, train, wx, run)
        snapshot, plan, case = prep.snapshot, prep.plan, prep.case
        _, logs, _ = await train
        run.update(intent="pro", route_by="single", roles=[Role.GENERAL.value],
                   readiness=case.readiness.level, risks=[x.key for x in case.risks])  # fmt: skip
        run["snapshot_failed"] = snapshot.failed
        run["_missing"] = missing_readings(snapshot.readings)
        if snapshot.failed:
            yield notice("这次没读到你的健康数据，下面的回答没有用到它。")
        blocked = next((x for x in case.risks if x.block), None)
        fixed_risk = (
            "\n\n".join(x for x in (prefix, blocked.note, RISK_BLOCK) if x) if blocked else ""
        )
        refusal_fixed, prefix = prefix, ""  # 拒答交给模型说，没提医生时再补（§86 需求 3）
        # 按意图选规程（§75）：和下面读条件、目标、指标同时进行
        routing = asyncio.create_task(route_skills(llm, text, history[-2:]))

        # 上下文：待确认的预览、今天的训练、排新计划要用的五项条件（旧答案带来源和日期）
        coach_lines = [x for x in history if not x.startswith(USER)]
        confirmed_now = bool(coach_lines) and HEAD in coach_lines[-1]
        previewed_now = bool(coach_lines) and CONFIRM_NOTE["plan"] in coach_lines[-1]
        confirmed = any(HEAD in x for x in coach_lines)
        target = await self._target(user_id, snapshot)
        terms = conditions(
            recall, snapshot.profile, target=target,
            plan_line=schedule_line(plan) if plan is not None else "", today=snapshot.today,
            checked_today=any(x.day == snapshot.today and x.done for x in logs),
        )  # fmt: skip
        follow = await self._context_for_follow(user_id, snap, train, run)
        aim = target or (GOALS[snapshot.profile.goal] if snapshot.profile.goal else "")
        kinds = [k for k in REFUSAL_KINDS if k in (run.get("refusals") or [])]
        refused = "；".join(_replies().refusals[k] for k in kinds)
        seen = await (self._earlier or earlier)(session_id)
        risk_notes = [x.note for x in case.risks if x.note not in seen and x is not blocked]
        ask_ill = await self._illness_followup(user_id, run)
        # 模型先判断、关键词兜底（§114）：下面几样先看路由（模型）的结果，路由出错才按关键词
        try:
            routed = await routing
        except Exception as e:  # 路由出错：退回按关键词
            _log.warning("skill route failed: error_type=%s", type(e).__name__)
            routed = None
        run["judged_by"] = "model" if routed is not None else "keyword"
        if routed is not None:  # 涉及训练：路由说的领域或选的规程里有训练
            training_ask = Role.TRAINER in routed.domains or any(
                x.role == Role.TRAINER for x in routed.skills
            )
        else:
            training_ask = asks_training(text) or bool(PLAN_REQUEST.search(text))
        # §5：危急指标又问训练时这一轮不给训练安排；话由模型说（§86）
        must_block = blocked is not None and (training_ask or asked(history) is not None)
        if (
            routed.sources if routed is not None else is_provenance(text)
        ):  # 追问上一条回答的来源（§86）
            sources = await (self._sources or last_sources)(session_id, SOURCES_ID)
            run["_provenance"] = provenance_note(sources)
        busy = (
            ""
            if routed is not None
            else "、".join(  # 这几天没空：模型看原话判断
                weekday_name(d) for d in sorted(blocked_days(text))
            )
        )
        if routed is None or any(x.id == "data-read" for x in routed.skills):  # 点名的指标先查好
            checked, checked_note = await self._check_named(
                user_id, session_id, text, [Role.GENERAL], run
            )
        else:
            checked, checked_note = None, ""
        note = "\n".join(x for x in (
            "现在的情况：\n" + "\n".join(follow) if follow else "",
            "排新计划要用的条件（旧答案带来源和日期）：\n" + "\n".join(terms),
            CONFIRMED_NOTE + (f"他的目标：{aim}。要写计划时，计划说明第一句写这份计划为了这个目标怎么排，目标的数和日期照写。" if aim else "")
            if confirmed_now else "",
            PREVIEWED_NOTE if previewed_now else "",
            f"他这句话说这些天没空：{busy}。挪训练不要挪到这些天。" if busy else "",
            files.note_for_experts(), checked_note,
            special_rules(special_flags(snapshot.profile, case.risks, snapshot.today)),
            f"他问的里面有你不能做的（诊断、开药改药、治疗方案、替他叫急救）。开头用一句自己的话说明这部分不能做、"
            f"该找谁，意思是：{refused} 再说能帮他做的部分。" if refused else "",
            run.get("_provenance", ""),
            f"数据里有危急情况：{blocked.note} 这一轮不给任何训练安排、不出计划、不写组数次数："
            "先把这件事跟他说清楚（先别运动、尽快就医、出现哪些情况马上打 120），再回答他问的里面和训练无关的部分。"
            if must_block and blocked else "",
            "回答涉及训练时要顺带提醒到（本会话说过的不用重复）：\n" + "\n".join(risk_notes)
            if risk_notes else "",
            f"今天还没问过他：{ask_ill} 回答末尾自然地问一句。" if ask_ill else "",
        ) if x)  # fmt: skip

        # Skill：跨领域先装 1–3 份，不够时由它自己再装。路由给了结果就只装它选的（加新用户、附图，
        # 这两样不是关键词）；关键词说的化验、动作、改计划、记训练只在路由出错时用（§114）
        records = record_kinds(text) if routed is None else set()
        asks_data = bool(records) and not _HURT.search(text)
        job_hint = task_of(text) if routed is None else None
        # 有伤病记忆、今天状态差不再强装伤痛处理、今天练不练（§111）：这两种情况写在各工作流的步骤里，
        # 档案照旧带着；路由按他问的选。规程上的 injury / poor 标记留着，问数据时去掉误选的伤痛规程（§37）
        triggers = {name for name, on in (
            ("plan", job_hint == "plan"), ("log", job_hint == "log"),
            ("image", bool(files.images)), ("move", bool(named_in(text))),
            ("new", plan is None and not logs and not recall.items),  # 新用户：一定装初次评估（§76）
            *((k, True) for k in records),
        ) if on}  # fmt: skip
        drop = {"injury", "poor"} if asks_data else set()
        if routed is not None:
            if routed.fit == "outside":  # 和健身无关的事（写周报）：新用户也不拉去评估
                triggers.discard("new")
            # 模型判断是打招呼、道谢、闲聊：不装规程（情况要求的也不装），也不给档案（§98）；
            # 附了图片、新用户例外（照片要估算，新用户要开始初次评估）
            chatting = routed.fit == "chat" and not triggers & {"image", "new"}
            loaded = (
                [] if chatting else pick_routed(routed.skills, routed.domains, text, triggers, drop)
            )
            run.update(skills_by="route", skill_intent=routed.intent, skill_fit=routed.fit)
            if routed.dropped:
                run["skills_dropped"] = routed.dropped
        else:  # 退回按关键词（都对不上时不按语义硬装，由 Agent 看目录自己装，§67）
            chatting = False
            # 路由看得到上一轮、关键词看不到：上一轮问过确认时补上排训练计划（§108 只在这里保留）
            loaded = pick_any(text, triggers | ({"plan"} if confirmed_now else set()), drop=drop)
            run["skills_by"] = "rule"
        run["skills"] = {Role.GENERAL.value: [x.id for x in loaded]}
        tools_ctx = self._tool_context(user_id, snapshot, case, recall, run.get("_found"))
        # 四层记忆（§73）：画像、情景、该问的、最近别的会话的摘要；查记忆工具查全部记忆
        raw = await self._memory_items(user_id)
        if not active_illness(run.get("_ill") or [], snapshot.today):
            # 没有正在进行的生病：跟生病有关的近期事件和建议不进四层记忆（§46 需求 7，和 recall 一样）
            raw = [
                x for x in raw if not (x.category in ("event", "advice") and mentions(x.content))
            ]
        lay = layers(raw, snapshot.today)
        try:
            earlier_sessions = await self._summary_store().latest(user_id, session_id, SHOW)
        except Exception as e:
            _log.warning("summary unavailable: error_type=%s", type(e).__name__)
            earlier_sessions = []
        memory_block = lay.text(snapshot.today, [
            f"{s.updated.astimezone().month}月{s.updated.astimezone().day}日：{s.text}" for s in earlier_sessions
        ])  # fmt: skip
        run["memory_layers"] = {"profile": len(lay.profile), "episodes": len(lay.episodes),
                                "asks": len(lay.asks), "summaries": len(earlier_sessions)}  # fmt: skip
        toolbox = Toolbox(
            GENERAL, kb=self._kb, health=self._health_source(), user_id=user_id,
            session_id=session_id, calcs=case.calcs, context=tools_ctx,
            meds=self._meds_source(), medical=self._medical_source(),
            extra={**EXTRA_TOOLS, RECALL: (RECALL_SCHEMA, recall_tool(raw, snapshot.today)),
                   **self._web_tools(snapshot.today), **self._timeline_tool(user_id, raw, snapshot.today)},
        )  # fmt: skip
        if checked is not None:
            toolbox.evidence.absorb(checked)
        personal = await basics
        run["basics"] = len(personal.lines)
        known = lay.handles
        using = "、".join(x.name for x in loaded)
        yield started(
            "agent",
            COACH_NAME,
            "理解问题、查资料和数据、作答" + (f"（规程：{using}）" if using else ""),
        )
        # 这一轮涉及训练才把计划和记录的写法放进系统提示（§96）
        # 路由给了结果按装上的规程（只问动作不用）；路由出错才按关键词（§114）
        on_training = (any(x.role == Role.TRAINER and x.id != "move-coach" for x in loaded)
                       or confirmed_now or previewed_now
                       or (routed is None and (job_hint is not None or training_ask)))  # fmt: skip
        run["actions_prompt"] = on_training
        run["chat_light"] = chatting  # §98：闲聊只给记忆和历史
        # 改计划、新计划、记训练是跟着规程装的工具（§120）；刚列了确认清单、他在回应（路由看了上一轮、
        # 选了排训练计划；路由不可用时看说法）却没交计划时，同一轮提醒它一次（§108：他问别的不提醒）
        replying = (any(x.id == "plan-build" for x in routed.skills) if routed is not None
                    else replies(text))  # fmt: skip
        ctx = Context.of(case)
        desk = Desk(
            self._action_handlers(user_id, text, plan, ctx, snapshot.today, run, tools_ctx,
                                  confirmed=confirmed, merge=bool(history), blocked=blocked is not None),
            has_plan=plan is not None, must_plan=confirmed_now and replying and blocked is None,
        )  # fmt: skip
        toolbox.actions = desk
        run["_desk"] = desk  # 这一轮出了异常时作废它存下的预览（generate_response 里）
        c = await respond(
            text, history, concerns_of(text), toolbox, llm, personal, recall, case=case, skills=loaded,
            note="" if chatting else note, with_case=not chatting,
            has_plan=plan is not None, confirmed=confirmed, just_asked=confirmed_now,
            today=snapshot.today, training=on_training,
            images=[x.part() for x in files.images], known=known, memory_block=memory_block,
        )  # fmt: skip
        yield finished("agent", consultation_summary(c), ok=c.status != "failed")
        run["_judged_state"] = c.status != "failed"  # 作答了：said 就是它的判断（没写就是没说）
        run["_said_state"] = c.opinion.said or {}
        if c.opinion.memory and self._remember_on:  # 这一轮要记的：核对后当场写入（§68）
            said["remembered"] = await self._remember_now(
                user_id, text, c.opinion.answer, c.opinion.memory, known, run, snapshot.today
            )
        loaded_more = [x.get("tool") for x in c.evidence.calls if x.get("tool") == "load_skill"]
        run["_experts"] = [{"role": Role.GENERAL.value, "status": c.status, **c.trace,
                            "calls": c.evidence.calls}]  # fmt: skip
        run["statuses"] = [c.status]
        run["queries"] = c.evidence.queries
        run["pro_tools"] = c.evidence.pro_queries
        run["tools"] = [str(x.get("tool")) for x in c.evidence.calls]
        if loaded_more:
            run["skills_loaded"] = len(loaded_more)
        if c.evidence.health_failed:
            yield notice("这次没读到你的健康数据，下面的回答没有用到它。")
        if c.opinion.speak:
            await desk.finish()  # 检查没过、它没再交的计划照出预览
        run["actions"] = desk.trace  # 只有工具名和结果类别（§120）
        if desk.unacted:
            run["unacted"] = True
        await self._drop_drafts(user_id, desk.stale)  # 同一轮被后一张换掉的计划预览
        if not c.opinion.speak:
            await self._drop_drafts(user_id, desk.drafts)
            run["path"] = "risk" if must_block else "no_answer"
            if must_block:
                run["risk_by"] = "fixed"
            said["answer"] = ""
            yield text_block(fixed_risk if must_block else "\n\n".join(
                x for x in (refusal_fixed, NO_ANSWER) if x))  # fmt: skip
            return

        own = plain(c.opinion.answer).strip()
        asks_terms = HEAD in own.split("\n\n")[0]  # 它决定先列条件请他确认（§55、§86）
        action = ("edit" if desk.plan is not None and plan is not None else "plan" if desk.plan is not None
                  else "log" if desk.logs else "new_plan" if desk.ask_new_plan or asks_terms else "none")  # fmt: skip
        run["action"] = action
        if blocked is not None and (action == "new_plan" or desk.tried_plan or desk.unacted):
            # 数据风险拦下训练安排（§5）：改计划、新计划这一轮本来就不给；它想改、要列条件排新计划、
            # 说了已经改了，都不用它的原文（原文可能说"已经改好了"）
            await self._drop_drafts(user_id, desk.drafts)
            run.update(action_dropped="risk", path="risk", risk_by="fixed")
            said["answer"] = ""
            yield text_block(fixed_risk)
            return
        if action == "new_plan":
            # 要新计划、本会话还没确认条件：由它用自己的话列出条件请他确认（§55、§86），不出预览；
            # 开头那段没有"排新计划前先确认一下"（下一轮靠它认出问过了）时，退回系统列的五项
            await self._drop_drafts(user_id, desk.drafts)
            ask = own if asks_terms else confirm_ask(terms)
            run.update(
                path="clarify", missing=["confirm"], clarify_by="model" if asks_terms else "fixed"
            )
            said["answer"] = ask
            yield text_block("\n\n".join(x for x in (refusal_fixed, ask) if x))
            return
        run["task"] = "plan" if desk.plan is not None else "log" if desk.logs else None
        run["_tail"] = ""  # 风险提醒、生病追问已经作为要求交给它（§86），不再拼在末尾

        def rules(answer: str) -> list[Violation]:
            return check_constraints(answer, ctx)

        def mark(answer: str) -> str:
            return annotate(answer, ctx)

        composed = await revise(c, text, llm, constraints=rules, memory=recall, annotate=mark)
        run.update(constraints=list(composed.violations), constraint_fixed=composed.fixed)
        run["_compose"] = {"checks": list(composed.checks), "repaired": composed.repaired,
                           "degraded": composed.degraded}  # fmt: skip
        if must_block:  # 危急指标：查它说到了先别运动、尽快就医，没给训练安排（§86 需求 2）
            lack = missing(composed.text, RISK_NEEDS)
            run["risk_by"] = "fixed" if lack else "model"
            if lack:
                await self._drop_drafts(user_id, desk.drafts)
                run["path"] = "risk"
                said["answer"] = ""
                yield text_block(fixed_risk)
                return
        unsaid = [k for k in kinds if missing(composed.text, REFUSAL_NEEDS[k])]
        if unsaid:  # 拒答没提医生（药师）：开头补上固定的一句（§86 需求 3）
            run["refusal_by"] = "fixed"
            prefix = "".join(_replies().refusals[k] for k in unsaid)
        elif refused:
            run["refusal_by"] = "model"
        prefix = "\n\n".join(x for x in (prefix, files.note_for_user()) if x)
        cards = desk.cards  # 动作工具出的预览（§120）：计划在前，训练记录在后
        if desk.plan is None and run.get("_plan_note"):  # 特殊人群拦下、最后没出计划预览（§95）
            composed = replace(composed, text=run["_plan_note"])
        if cards:
            # 系统另外换了动作、有没改的：它没说到的补一句，和卡片一致
            left = [x for x in run.pop("_plan_notes", []) if x not in composed.text]
            extra = f"另外：{'；'.join(left)}。" if left else ""
            extra_note = "\n\n".join(
                x for x in (extra, *(CONFIRM_NOTE[k] for k in desk.kinds)) if x
            )
            composed = replace(composed, text=composed.text.rstrip() + "\n\n" + extra_note)
        blocks = self._answer(composed, prefix, run, said)
        tail = 2 if blocks[-1].get("tool_call_id") == SOURCES_ID else 0
        for block in [*blocks[: len(blocks) - tail], *cards, *blocks[len(blocks) - tail :]]:
            yield block
        run.pop("_desk", None)  # 卡片发出去了：后面再出什么事也不作废它们
        await self._drop_drafts(user_id, desk.replaced)  # 新的那张给他看了：上一轮那张作废

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

    async def _context_for_follow(
        self,
        user_id: str,
        snap: asyncio.Task[Snapshot],
        train: asyncio.Task[tuple[Plan | None, list[WorkoutLog], date | None]],
        run: dict[str, Any],
    ) -> list[str]:
        """路由没把握时管家看的上下文（spec [2026-10-23] §56）：待确认的计划预览、今天的训练状态、计划目标。"""
        out: list[str] = []
        try:
            draft = await self._training_store().pending_plan(user_id)
        except Exception as e:
            _log.warning("pending plan unavailable: error_type=%s", type(e).__name__)
            draft = None
        drafted = parse_plan(draft.content.get("plan"))[0] if draft is not None else None
        if drafted is not None:
            days = "、".join(
                f"{weekday_name(x.day)}{x.name}约 {x.minutes} 分钟" for x in drafted.sessions
            )
            goal = f"，目标：{drafted.goal}" if drafted.goal else ""
            out.append(
                f"待确认的计划预览（上一轮给的）：每周练 {drafted.days_per_week} 次（{days}）{goal}"
            )
        try:
            snapshot, (plan, logs, _) = await snap, await train
        except Exception as e:
            _log.warning("training unavailable: error_type=%s", type(e).__name__)
            return out
        if plan is not None:
            today = snapshot.today
            s = plan.session_on(today)
            done = any(x.day == today and x.done for x in logs)
            out.append(f"今天按计划：{s.name if s else '休息'}" + ("，已打卡完成" if done else ""))
            if plan.goal:
                out.append(f"当前计划的目标：{plan.goal}")
        run["follow_context"] = {"preview": drafted is not None, "lines": len(out)}
        return out

    def _action_handlers(
        self,
        user_id: str,
        text: str,
        current: Plan | None,
        ctx: Context,
        today: date,
        run: dict[str, Any],
        tools: ToolContext | None,
        *,
        confirmed: bool,
        merge: bool,
        blocked: bool,
    ) -> dict[str, Handler]:
        """动作工具的处理（spec [2026-10-23] §120）：校验、套用、检查、存成预览，结果当场交还给管家。

        套用和检查沿用 §45、§12、§95、§108；危急情况（§5）这一轮不给改计划和新计划。日志只记结果类别。
        """
        store = self._training_store()

        async def edit(desk: Desk, args: Mapping[str, Any]) -> Outcome:
            ops = parse_ops(args.get("ops")) if current is not None else None
            if not ops or tools is None or current is None:
                return Outcome(
                    False,
                    "操作没写对：ops 要是工具说明里那六种操作的列表，每条写清哪天、哪个动作。",
                    "format",
                )
            busy = tuple(x for x in args.get("busy") or () if isinstance(x, int) and 1 <= x <= 7)
            scope = str(args.get("scope") or "")
            cards, say, draft = await self._ops_preview(
                user_id, text, current, ops, ctx, tools, run, by="model",
                merge=merge or desk.plan is not None,
                busy=busy if "busy" in args else None, scope=scope if scope in SCOPES else "",
                replaced=desk.replaced,
            )  # fmt: skip
            if not cards:
                return Outcome(
                    False, say + "（这次没出预览：照这个跟他说，或者改了再交。）", "rejected"
                )
            run["_plan_notes"] = [*run.get("_plan_notes", []), *run.pop("_plan_changed_notes", [])]
            return Outcome(
                True, "已出预览，等他确认。" + say, kind="plan", cards=tuple(cards), draft=draft
            )

        async def new_plan(desk: Desk, args: Mapping[str, Any]) -> Outcome:
            # 新排一份要先确认条件（§55）；在现有计划上换分化、重排不用（§108）
            # 没有计划时谈不上在现有计划上重排；有计划时只有明说 new 才算新排
            fresh = current is None or args.get("kind") == "new"
            if fresh and not confirmed:
                return Outcome(False, f"本会话还没确认过排新计划的条件：这一轮不出计划，回答以「{HEAD}」开头，"
                               "把条件列给他确认。", "confirm")  # fmt: skip
            raw = args.get("plan")
            new, why = parse_plan(raw)
            if new is None:
                return Outcome(False, f"计划没写对（{why}），按工具说明的格式改好再交。", "format")
            new = annotate_plan(new, ctx)
            if tools is not None:
                problems = self._plan_problems(new, current, tools, text)
                special = [x for x in problems if is_special(x)]
                if (
                    special
                ):  # 特殊人群的硬规则（§95）：不出预览；最后没出预览时用固定说明，不交给它说
                    run.update(preview="blocked_special", special=sorted(tools.special))
                    run["_plan_note"] = ("这份计划有不适合你现在情况的地方，我先不给你出预览：\n"
                                         + "\n".join(f"- {plain(x)}" for x in special)
                                         + "\n可以换个说法让我重排，或者先问问医生能练到什么强度。")  # fmt: skip
                    return Outcome(False, "这份计划有不适合他现在情况的地方，没出预览：" + "；".join(plain(x) for x in special)
                                   + "。改掉再交。", "special")  # fmt: skip
                if (
                    problems and not desk.rejected["check"]
                ):  # 计划检查没过：退回一次，改了再交（§12）
                    run["plan_check"] = "failed"
                    desk.fallback = lambda: new_plan(desk, args)  # 它没再交：这一份照出预览
                    return Outcome(
                        False, "计划检查没过，改好再完整交一次：" + "；".join(problems), "check"
                    )
                run["plan_check"] = (
                    "fixed"
                    if desk.rejected["check"] and not problems
                    else ("partly" if problems else "pass")
                )
            if current is not None and same_training(new, current):
                run["preview"] = "unchanged"  # 和现在的一样：不出"沿用不变"的预览（§108）
                return Outcome(
                    False,
                    "和他现在的计划一样，不出预览：跟他说现在的计划已经是这样，不用改。",
                    "unchanged",
                )
            changes = str(args.get("changes") or "")[:120]
            run.pop("_plan_notes", None)  # 整份换掉了：之前改计划时系统换动作的说明不再适用
            draft = await store.add_draft(user_id, "plan", plan_content(new, changes))
            run["preview"] = "plan"
            return Outcome(True, "已出预览，等他确认。", kind="plan", cards=tuple(plan_card(draft, new, current)),
                           draft=draft.id)  # fmt: skip

        async def log_workout(desk: Desk, args: Mapping[str, Any]) -> Outcome:
            log, why = parse_log(dict(args), today)
            if log is None:
                return Outcome(False, f"记录没写对（{why}），按工具说明的格式改好再交。", "format")
            log = trusted_log(log, text, current)  # 数字只来自他的话
            draft = await store.add_draft(user_id, "log", log_content(log))
            run["preview"] = "log"
            return Outcome(True, "已出训练记录预览，等他确认。", kind="log", cards=tuple(log_card(draft, log)),
                           draft=draft.id)  # fmt: skip

        handlers: dict[str, Handler] = {LOG_WORKOUT: log_workout}
        if not blocked:
            handlers[NEW_PLAN] = new_plan
            if current is not None:
                handlers[PLAN_EDIT] = edit
        return handlers

    async def _drop_drafts(self, user_id: str, ids: Sequence[str]) -> None:
        """这一轮没给他看到的预览作废。"""
        for x in ids:
            try:
                await self._training_store().cancel(user_id, x)
            except Exception as e:
                _log.warning("draft cancel failed: error_type=%s", type(e).__name__)

    def _plan_problems(
        self, plan: Plan, current: Plan | None, tools: ToolContext, text: str
    ) -> tuple[str, ...]:
        """计划检查（§12）；按复盘调整时每次最多改两天（§18）。"""
        limit = REVIEW_MAX_DAYS if text.startswith(REVIEW_ASK) else None
        return check_plan(plan, current=current, goal=tools.goal, injured=tools.injured,
                          equipment=tools.equipment, max_changed_days=limit, special=tools.special).problems  # fmt: skip

    async def _ops_preview(
        self,
        user_id: str,
        text: str,
        current: Plan,
        ops: list[Op],
        ctx: Context,
        tools: ToolContext,
        run: dict[str, Any],
        *,
        by: str,
        merge: bool,
        busy: tuple[int, ...] | None = None,
        scope: str = "",
        replaced: list[str] | None = None,
    ) -> tuple[list[dict[str, Any]], str, str]:
        """按操作改计划（spec [2026-10-23] §45）：代码套用、时长超了先减辅助动作、注明伤病限制，存成预览。

        同一段对话里上一份预览还没确认时，在它上面接着改，合成一张，旧的那张作废。
        哪几天没空、只改这次还是以后都这样，按管家写的（§114）；它没写这两项才按关键词。
        返回（预览卡片, 给用户的话, 预览编号）；日志只记操作的条数，不记内容。
        """
        store = self._training_store()
        prior = None
        if merge:
            try:
                prior = await store.pending_plan(user_id)
            except Exception as e:
                _log.warning("pending plan unavailable: error_type=%s", type(e).__name__)
        base = parse_plan(prior.content.get("plan"))[0] if prior is not None else None
        if base is None:
            prior, base = None, current
        try:
            applied = fit_time(apply(base, ops, equipment=tools.equipment, injured=tools.injured,
                                     blocked=set(busy) if busy is not None else blocked_days(text)))  # fmt: skip
        except Conflict as e:
            run["plan_ops"] = {"by": by, "ops": len(ops), "conflict": True}
            return [], f"{e}，{CONFLICT_ASK}", ""
        run["plan_ops"] = {"by": by, "ops": len(applied.done), "skipped": len(applied.skipped),
                           "merged": prior is not None,
                           "limits_by": "model" if busy is not None or scope else "keyword"}  # fmt: skip
        if not applied.done:
            took = "、".join(dict.fromkeys(meant(o) for o in ops))
            reasons = "；".join(applied.skipped)
            return (
                [],
                f"我理解成要{took}，但没改成：{reasons}。你是想改计划的哪一处，还是重新排一份？"
                "改某一处就说具体哪天、哪个动作；要重新排就回「重新排一份」。",
                "",
            )
        new = annotate_plan(applied.plan, ctx)

        def review(p: Plan) -> tuple[str, ...]:
            return check_plan(p, current=current, goal=tools.goal, injured=tools.injured,
                              equipment=tools.equipment, special=tools.special).problems  # fmt: skip

        # 只看这次改动新带来的问题（原计划本来就有的不算）；有就不出预览（§48）
        had = {_no_day(x) for x in review(base)}
        left = [x for x in review(new) if _no_day(x) not in had]
        # 他明说删掉某天时，那天练的肌群没了是他要的结果：照改，提醒一句；换动作带丢的才挡下
        dropped_day = any(o.kind == "remove" and not o.exercise for o in applied.done)
        warn = [x for x in left if dropped_day and "没练到" in x]
        left = [x for x in left if x not in warn]
        run["plan_check"] = "pass" if not left else "failed"
        if left:
            return (
                [],
                "这样改会有问题：" + "；".join(left) + "。这次没改，换个说法告诉我想怎么改。",
                "",
            )
        applied.notes.extend(x.split("：")[0] for x in warn)
        run["_plan_changed_notes"] = [*applied.notes, *applied.skipped]
        changes = applied.changes
        earlier_ops: list[Any] = []
        if prior is not None:
            earlier_ops = list(prior.content.get("ops") or [])
            changes = "；".join(x for x in (str(prior.content.get("changes") or ""), changes) if x)
        extra = describe(applied)
        draft = await store.add_draft(
            user_id, "plan",
            plan_content(new, changes, ops=earlier_ops + extra["ops"], skipped=extra["skipped"],
                         hint=(SCOPE_HINT if scope == "unclear" else "") if scope else scope_hint(text)),
        )  # fmt: skip
        if prior is not None and replaced is not None:
            replaced.append(
                prior.id
            )  # 他看到新的这张以后才作废旧的（§120：这一轮没答出来时旧的还能确认）
        elif prior is not None:
            await store.cancel(user_id, prior.id)
        run["preview"] = "plan"
        say = "按你说的改好了：" + "；".join(applied.lines) + "。"
        if applied.notes:
            say += "另外：" + "；".join(applied.notes) + "。"
        if applied.skipped:
            say += "没改的：" + "；".join(applied.skipped) + "。"
        return plan_card(draft, new, current), say, draft.id

    async def _insights(
        self,
        user_id: str,
        snapshot: Snapshot,
        logs: Sequence[WorkoutLog],
        ill: Sequence[Episode],
        recall: Recall,
    ) -> tuple[list[Any], list[tuple[str, str]]]:
        """读懂指标趋势（§84）：代码算好的事实；再加上管家今天复盘后已经做了的调整（§85，读不到当作没有）。
        返回（认出的情况, 给档案的 (一句话, 依据) 列表）。"""
        from ironm_agent.illness import active as active_ill
        from ironm_agent.illness import ago
        from ironm_agent.insights import situations

        today = snapshot.today
        events = [x.content for x in recall.items if x.category == "event" and x.status == "active"]
        sick = [f"{ago(e.started, today)}说{e.what()}" for e in active_ill(ill, today)]
        found = situations(snapshot.readings, snapshot.profile, today, logs=logs, illness=sick,
                           events=events)  # fmt: skip
        lines = [(f"看到的：{s.line()}", s.detail()) for s in found]
        state = await self._coach_state(user_id)
        review = state.review if state is not None else None
        if review is not None and review.day == today:
            lines += [(f"管家今天已经调整：{d.title}（原因：{d.why}）", f"{d.title}。原因：{d.why}。依据：{d.basis}")
                      for d in review.done if not d.undone]  # fmt: skip
            lines += [(f"管家今天核对了以前的调整：{x}", x) for x in review.checked]  # §89
        if state is not None and state.stage_text and state.stage_day is not None:
            when = f"{state.stage_day.month}月{state.stage_day.day}日"
            lines.append((f"最近一次 4 周阶段小结（{when}）：{state.stage_text}", state.stage_text))
        return found, lines

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
        ill: list[Episode] = list((run or {}).get("_ill") or [])
        lines = case_lines(plan, logs, snapshot.today, since)
        recovering = recovering_days(ill, snapshot.today)  # 生病期间的组次不触发减重量（§46）
        steady = [x for x in logs if x.day not in recovering]
        mode = today_mode(ill, snapshot.today, trained_since=[x.day for x in logs if x.done])
        # 交给模型的是"今天怎么练"那句（相对的说法、带做法），不给日期和"现在还没好"，免得照着念（§82）
        state = (mode[1] if mode else "") or state_line(ill, snapshot.today)
        level: Literal["poor", "fair"] = "poor" if mode and mode[0] == "rest" else "fair"
        signal = (level, state) if mode is not None else None  # 病后第一次也告诉角色：按约七成
        day = (run or {}).get("_day")
        at = (run or {}).get("_at")
        today_lines = await self._today_lines(user_id, plan, snapshot.today, day, ill)
        found, insight_lines = await self._insights(user_id, snapshot, logs, ill, recall)
        if run is not None:
            run["_found"] = found
        case = build_case(
            snapshot, recall, text, plan=lines + target_lines(plan, steady, snapshot.today),
            illness=signal, day=today_lines, earlier=day_signals(day, before=at),
            insights=insight_lines,
        )  # fmt: skip
        current = await wx if wx is not None else None
        if current is not None:
            case = replace(case, weather=_weather_case(current, plan, snapshot.today))
        if run is not None:
            run["weather"] = current is not None
        has_plan = plan is not None
        planning = wants_new(text, has_plan=has_plan) or asked(history) is not None
        target = await self._target(user_id, snapshot) if planning else ""
        decision = decide(
            text, history, recall, snapshot.profile, has_plan=has_plan, target=target,
            plan_line=schedule_line(plan) if plan is not None else "", today=snapshot.today,
            checked_today=any(x.day == snapshot.today and x.done for x in logs),
        )  # fmt: skip
        if decision.new and not decision.ask:  # 排新计划：按具体目标说明怎么排（§55 需求 2）
            aim = target or (GOALS[snapshot.profile.goal] if snapshot.profile.goal else "")
            if aim:
                said = f"他的目标：{aim}。计划说明第一句写这份计划为了这个目标怎么排，目标的数和日期照写。"
                decision = replace(decision, note="\n".join(x for x in (decision.note, said) if x))
        return Prepared(snapshot, plan, case, decision)

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
        blocks.append(
            text_block(answer_text(composed, prefix=prefix, suffix=run.get("_tail") or ""))
        )
        sources = sources_text(composed)
        if sources:  # 出处不写进正文，放进可展开的“依据与来源”
            blocks.append(started(SOURCES_ID, SOURCES_NAME, "这条回答用到的资料、计算和你的数据"))
            blocks.append(finished(SOURCES_ID, sources))
        return blocks
