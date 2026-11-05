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
from collections.abc import (
    AsyncGenerator,
    AsyncIterator,
    Awaitable,
    Callable,
    Coroutine,
    Mapping,
    Sequence,
)
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from functools import cache, partial
from typing import Any, Literal, cast

from ironm_agent.actions import (
    ADJUST_TODAY,
    KCAL_CHANGE,
    LOG_BODY,
    LOG_MEAL,
    LOG_WORKOUT,
    NEW_PLAN,
    PLAN_EDIT,
    RECORD_STATE,
    REMEMBER,
    SET_GOAL,
    TEMP_CHANGE,
    Desk,
    Handler,
    Outcome,
)
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
    asked,
    conditions,
    confirm_ask,
    replies,
)
from ironm_agent.compose import Composed, revise
from ironm_agent.constraints import Context, Violation, annotate, annotate_plan
from ironm_agent.constraints import check as check_constraints
from ironm_agent.day_state import DayState, DayStore, default_day
from ironm_agent.day_state import lines as day_lines
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
    question,
    recovering_days,
)
from ironm_agent.illness import active as active_illness
from ironm_agent.illness import (
    recent as recent_illness,
)
from ironm_agent.illness import summary_line as illness_line
from ironm_agent.indicators import named_indicators, record_kinds
from ironm_agent.kb import KnowledgeBase, default_kb
from ironm_agent.llm import ModelsConfig, ModelUnavailable, TurnLLM, load_models
from ironm_agent.memory import (
    COACH,
    USER,
    earlier,
    last_sources,
    recent,
    split_thread,
    user_lines,
    whole,
)
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
from ironm_agent.memory_store import Change, Item, MemoryStore, default_store
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
    goal_card,
    log_card,
    notice,
    plan_card,
    sections_text,
    sources_text,
    started,
    temp_card,
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
    DRAFT_HOURS,
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
# 每个人用自己的模型（§167）：没填时普通问题这样回；急症、红旗照样按规则给固定的安全回答
NO_MODEL_CHAT = "先在「我 → 模型和 API」填你自己的模型，IronM 才能回答。记训练、看计划不用填也能用。"
SETTINGS_DOWN = "读不到你的模型设置，请稍后再试。"


class _NoModel:
    """没有可用的模型（§167）：调用一律失败，安全前置退回固定回答；其余这一轮不作答。"""

    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def chat(self, *_: Any, **__: Any) -> Any:
        raise ModelUnavailable("no_model")
CONFLICT_ASK = (
    "我没法确定你想怎么改。请分开说：先说一条，确认后再说下一条。"  # 改计划的要求互相矛盾时（§45）
)
REVIEW_ASK = "按这周的复盘调整训练计划"  # 每周复盘一键生成调整方案时的问法（spec [2026-10-23] §18）
REVIEW_MAX_DAYS = 2  # 按复盘调整每次最多改几天
SCOPES = ("once", "always", "unclear")  # 改计划只改这次、以后都这样、没说清（§114）
STATE_FIELDS = (
    "sick",
    "sick_level",
    "better",
    "tired",
    "sleep",
    "minutes",
    "good",
    "pain",
)  # 今天的状态（§114、§122）
BODY_KINDS = (
    "weight",
    "body_fat",
    "waist",
    "resting_hr",
    "systolic",
    "diastolic",
)  # 对话里能记的读数
MEAL_KINDS = ("早餐", "午餐", "晚餐", "加餐", "夜宵", "练前", "练后")
MAX_FOODS = 12  # 一餐最多几样（同饮食页）


_NOT_GOAL = re.compile(r"(?:不想|不再|不要|不是|别|不用|不打算|放弃)[^，。！？,.!?\n]{0,4}$|不$")
_NOT_AFTER = re.compile(r"^[^，。！？,.!?\n]{0,3}(?:不想|不要|不练|不干|不搞|算了|放弃)")


def _said_goal(kind: str, text: str) -> bool:
    """他说了这个目标方向（"不想再继续减脂""我不减脂了""减脂我不想了"里的减脂不算）。"""
    return any(
        not _NOT_GOAL.search(text[max(0, m.start() - 8) : m.start()])
        and not _NOT_AFTER.search(text[m.end() : m.end() + 8])
        for m in _GOAL_WORDS[kind].finditer(text)
    )


# 目标方向的说法（§151：交的类型要和他这句话对得上）
_GOAL_WORDS: dict[str, re.Pattern[str]] = {
    "fat_loss": re.compile(r"减脂|减肥|减重|瘦|掉秤|降体脂|刷脂|减到|降到"),
    "muscle": re.compile(r"增肌|长肌肉|练大|增重|变壮|围度|增到|长到"),
    "strength": re.compile(r"力量|增力|变强|大重量|极限|1RM", re.I),
    "endurance": re.compile(r"耐力|马拉松|跑得更久|长跑|有氧能力|体能"),
    "health": re.compile(r"健康|身体好|保持|维持"),
}


def _in_jin(raw: str, unit: Any, text: str) -> bool | None:
    """体重他说的是不是斤：原话里这个数后面跟着"斤"或"公斤"按原话；否则看单位参数；没写单位时，
    原话只出现"斤"（含"一百四十斤"这类中文数字）算斤、只出现"公斤"或都没有算公斤，两样都有说不清（None）。"""
    after = re.search(r"(?<![\d.])" + re.escape(raw) + r"\s*(公斤|斤)", text)  # "170 斤"里的"70"不算（复核 11-03）
    if after:
        return after.group(1) == "斤"
    if unit in ("斤", "公斤"):
        return bool(unit == "斤")
    jin, kg = re.search(r"(?<!公)斤", text) is not None, "公斤" in text
    if jin and kg:
        return None
    return jin


def _metric_value(snapshot: Snapshot | None, key: str) -> float | None:
    """档案里算好的一个指标的值（算不出来是 None）。"""
    m = next((x for x in snapshot.metrics if x.key == key), None) if snapshot is not None else None
    return float(m.value) if m is not None and m.value is not None else None


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


RETHINK = ("说了今天的状态",)  # 这些事之后管家重看今天（§163 需求 3）


async def default_coach_eval(user_id: str, reason: str, force: bool) -> None:
    """管家重新评估当前方案，用线上的存储（测试里换掉）。"""
    from ironm_agent.coach_state import evaluate
    from ironm_agent.web_more import coach_deps

    deps = coach_deps()
    await evaluate(user_id, deps, reason=reason, force=force)
    wake_review(user_id, deps, reason, force)


def wake_review(user_id: str, deps: Any, reason: str, force: bool) -> None:
    """评估之后要不要叫醒管家复盘：每天第一次提问跑当天的（§85）；他说了身体的事重看今天，不按规则改（§163）。"""
    from ironm_agent import review

    if not force:
        review.daily_later(user_id, deps)
    elif reason in RETHINK:
        review.rerun_later(user_id, deps, reason)


RISK_BLOCK = "这一轮先不给训练安排。饮食、睡眠或者你的数据，可以照常问我。"
CONFIRM_NOTE = {
    "plan": "下面是计划预览，点「确认」才会保存，保存后也能撤销。",
    "log": "下面是这次训练的记录预览，点「确认」才会记下。",
    "goal": "下面是改目标的预览，点「确认」才会改，改了也能撤销。",  # §151
    "temp": "下面是临时调整的预览，点「确认」才生效，到了结束日期自动回到原计划，也能提前撤销。",  # §163
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


MEMORY_CAP = 8  # 一轮最多交几条记忆（和后台提取一轮最多落几条一样，§145）


def _memory_holds(
    ops: Sequence[Mapping[str, Any]], known: Mapping[str, Any], text: str, answer: str, today: date
) -> bool:
    """这一轮交的记忆按回答核对后，有没有通过的长期情况（近况不算：一次训练被记成近况，不能顶替记训练）。"""
    from ironm_agent.memory_extract import validate

    if not ops:
        return False
    checked, _ = validate({"ops": list(ops)}, known, text, answer, today=today)
    return any(x.category != "event" for x in checked)


@dataclass(frozen=True)
class Prepared:
    snapshot: Snapshot
    plan: Plan | None
    case: CaseFile


def _weather_case(w: Weather, plan: Plan | None, today: date) -> str:
    """共享档案里的天气（spec [2026-10-23] §34）：现在的天气、未来几天的预报。代码不再按天气改本周的训练
    （§163），要不要改由管家看这些自己定。"""
    from ironm_agent.weather_plan import forecast_line

    parts = [weather_line(w)]
    ahead = forecast_line(w.days, today)
    if ahead:
        parts.append(f"未来几天：{ahead}")
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


async def _steps_until(
    task: asyncio.Task[Any], steps: asyncio.Queue[tuple[str, str, str, bool | None]]
) -> AsyncIterator[dict[str, Any]]:
    """作答进行时，把每一步的开始和结束发给页面（§165）；作答完了把剩下的发完。"""
    while True:
        getting = asyncio.ensure_future(steps.get())
        try:
            done, _ = await asyncio.wait({task, getting}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            if not getting.done():
                getting.cancel()
        if getting not in done:
            break
        yield _step_block(getting.result())
    while not steps.empty():
        yield _step_block(steps.get_nowait())


def _step_block(e: tuple[str, str, str, bool | None]) -> dict[str, Any]:
    sid, name, detail, ok = e
    return started(sid, name, detail) if ok is None else finished(sid, "", ok=ok)


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
        self._readings: Any = (
            None  # 自己记的读数、饮食记录、热量调整（§122 对话里记；None 用线上的）
        )
        self._meals: Any = None
        self._diet: Any = None
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
        # 今天的状态、记忆在回答发出后由管家在后台读了再记（§166）；False 时照 §122、§145 作答时当场调工具
        self._record_after = True
        self._observe = observe
        self._locks: dict[str, asyncio.Lock] = {}  # 同一个人的记忆提取一次只跑一个
        self._tasks: set[asyncio.Task[None]] = set()  # 后台提取记忆的任务
        # 每个人还没写完的档案与记忆更新：下一轮作答前先等它们做完（spec [2026-10-23] §51）
        self._pending: dict[str, set[asyncio.Task[None]]] = {}
        self._sync_wait = SYNC_WAIT_S
        self._health = health
        self._kb = kb or default_kb()
        # 显式给了模型配置（评测、回放的本机直跑）就用它；网页和 App 的问答用每个人自己填的（§167）
        self._fixed = models is not None
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

    async def _own_llm(self, user_id: str) -> TurnLLM | None:
        """这个人自己填的模型（§167，没有默认模型）；没填返回 None，读不到设置时抛出。"""
        if self._fixed:
            return TurnLLM(self._models, self._environ)
        from ironm_agent import user_models

        got = await user_models.own_config(user_id)
        return None if got is None else TurnLLM(*got)

    async def _quiet_llm(self, user_id: str) -> TurnLLM | None:
        """后台的事（摘要、记忆、读身体情况）用：没填或读不到设置都返回 None，这一步就不做（§167）。"""
        try:
            return await self._own_llm(user_id)
        except Exception as e:
            _log.warning("user model unavailable: error_type=%s", type(e).__name__)
            return None

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
            injured=tuple(dict.fromkeys([*case.injuries, *case.sore])),  # 最近说疼的：排计划、换动作也避开（§158）
            equipment_items=recall.items,  # 读字段（§150）
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

    async def _paused(self, user_id: str) -> bool:
        """他暂停了记忆没有；读不到当作没暂停（写入时还会再看一次）。"""
        try:
            return bool(await self._memory_store().paused(user_id))
        except Exception as e:
            _log.info("memory pause unknown: error_type=%s", type(e).__name__)
            return False

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
        """这个人的记忆（含被取代、已结束的，归档了的不取，§157），四层记忆用；读不到时当作没有。"""
        try:
            return await self._memory_store().items(user_id, current_only=False, recent=date.today())
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
            items = await store.items(user_id, current_only=False, recent=today)
            pains = await self._pain_store().since(user_id, today - timedelta(days=PAIN_DAYS))
            from ironm_agent.body_now import fresh

            pains = fresh(pains, items)  # 说好了的那处，之前的疼不再算（§158）
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
            if (llm := await self._quiet_llm(user_id)) is None:  # 用他自己的模型，没填不写摘要（§167）
                return
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

    async def _goal_preview(
        self, user_id: str, text: str, today: date, snapshot: Snapshot | None,
        args: Mapping[str, Any], store: Any,
    ) -> Outcome:  # fmt: skip
        from ironm_agent.goal import Goal, progress
        from ironm_agent.memory_extract import digits
        from ironm_agent.metrics import GOALS, compute_all

        if snapshot is None or snapshot.failed:  # 读不到档案：原来的目标不知道，撤销会清掉真实的（复核 11-03）
            return Outcome(False, "这次读不到他的档案，改不了目标；请他稍后再说一次。", "error")
        kind = str(args.get("type") or "")
        value, by_raw = args.get("value"), str(args.get("by") or "")
        if not kind and value is None:
            return Outcome(False, "要交目标方向（type）或目标体重和日期（value、by）。", "format")
        if value is None and by_raw:  # 只交日期：目标表要体重和日期一起，不能悄悄丢掉
            return Outcome(False, "目标日期要和目标体重（value）一起交；他没说体重就先问他。", "format")
        if kind and (kind not in GOALS or not _said_goal(kind, text)):
            return Outcome(
                False,
                "目标方向和他这句话的说法对不上：他说了减脂、增肌、增力、耐力或健康才交。",
                "goal",
            )
        kg: float | None = None
        by: date | None = None
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, int | float):
                return Outcome(False, "目标体重写他说的数。", "format")
            raw = f"{float(value):g}"
            if raw not in digits(text, chinese=True):
                return Outcome(
                    False,
                    "这个目标体重不在他这句话里：写他说的数，说斤写斤的数、unit 写斤。",
                    "number",
                )
            jin = _in_jin(raw, args.get("unit"), text)
            if jin is None:
                return Outcome(False, "说不清是斤还是公斤：先问他一句。", "number")
            kg = round(float(value) / 2, 1) if jin else float(value)
            if not 30 <= kg <= 250:
                return Outcome(False, "目标体重要在 30–250 公斤之间。", "number")
            try:
                by = date.fromisoformat(by_raw)
            except ValueError:
                return Outcome(
                    False, "目标体重要配一个日期（by，YYYY-MM-DD）；他没说哪天就先问他。", "format"
                )
            if not today < by <= today + timedelta(days=730):
                return Outcome(False, "目标日期要在今天之后、两年以内（和目标页一样）。", "format")
        before = snapshot.profile.goal
        try:
            old = await self._goal_store().get(user_id)
        except Exception as e:  # 读不到目标表：当作没有
            _log.info("goal unavailable: error_type=%s", type(e).__name__)
            old = None
        after = cast("Any", kind) if kind else before
        if after == before and kg is None:
            return Outcome(False, f"目标已经是{GOALS.get(str(before), '')}，不用改。", "same")

        def kcal(goal: Any) -> float | None:
            p = replace(snapshot.profile, goal=goal)
            got = next(
                (m for m in compute_all(snapshot.readings, p, today) if m.key == "kcal_target"),
                None,
            )
            return float(got.value) if got is not None and got.value else None

        now_kcal = _metric_value(snapshot, "kcal_target")  # 首页现在的目标（带着两周复盘的调整量）
        items = []
        if kind and after != before:
            items.append(
                f"目标：{GOALS.get(str(before), '没填') if before else '没填'} → {GOALS[kind]}"
            )
        k0, k1 = kcal(before), kcal(after)
        if now_kcal and k0 and k1:  # 和首页同一个数起算，只加目标类型带来的变化
            k0, k1 = now_kcal, now_kcal + (k1 - k0)
        if k1 and k0 != k1:
            items.append(
                f"每日热量：约 {round(k0)} → {round(k1)} 千卡"
                if k0
                else f"每日热量：约 {round(k1)} 千卡"
            )
        if kg is not None and by is not None:
            was = f"（原来 {old.value:g} 公斤）" if old is not None else ""
            items.append(f"目标体重：{kg:g} 公斤，{by.year}年{by.month}月{by.day}日前{was}")
            trend = next((m for m in snapshot.metrics if m.key == "weight_trend"), None)
            pace = progress(Goal(kg, by, today), snapshot.readings.weight, trend, today).get("pace")
            if pace:
                items.append(str(pace))
        content = {"title": "改目标", "headline": str(args.get("why") or "")[:60] or "确认后才改",
                   "items": items,
                   "goal": {"type": kind or None, "value": kg, "by": by.isoformat() if by else None},
                   "before": {"type": before, "goal": old.json() if old is not None else None}}  # fmt: skip
        try:  # 上一轮出的改目标卡片还没处理：作废，免得他点了旧的（复核 11-03）
            prior = await store.pending_plan(user_id, DRAFT_HOURS * 60, kind="goal")
        except Exception as e:
            _log.info("goal draft lookup failed: error_type=%s", type(e).__name__)
            prior = None
        draft = await store.add_draft(user_id, "goal", content)
        if prior is not None:
            await self._drop_drafts(user_id, [prior.id])
        return Outcome(True, "已出改目标预览卡片，等他确认（确认前目标没改）。", kind="goal",
                       cards=tuple(goal_card(draft, content)), draft=draft.id, what="goal")  # fmt: skip

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

    def _readings_store(self) -> Any:
        """自己记的读数（体重、腰围……）写进健康记录（§26）；测试里换成内存版。"""
        if self._readings is None:
            from ironm_agent.readings import default_readings

            self._readings = default_readings()
        return self._readings

    def _meals_store(self) -> Any:
        if self._meals is None:
            from ironm_agent.meals import default_meals

            self._meals = default_meals()
        return self._meals

    def _diet_store(self) -> Any:
        if self._diet is None:
            from ironm_agent.diet_adjust import default_diet

            self._diet = default_diet()
        return self._diet

    async def _read_day(self, user_id: str, run: dict[str, Any]) -> DayState | None:
        """今天的状态（只读）；读不到当作没有。"""
        run["_at"] = datetime.now(UTC)
        try:
            return await self._day_store().get(user_id, date.today())
        except Exception as e:
            _log.warning("day state unavailable: error_type=%s", type(e).__name__)
            return None

    def _memory_context(self, history: list[str]) -> list[str]:
        """后台提取记忆时给的前文：他前面说的话；§166 起作答时不当场记，再带上管家上一句的结尾
        （"还是这样吗""好些了吗"在那里），他回"还是""好了"才知道是在确认哪一条。"""
        lines = user_lines(history)
        coach = next((x for x in reversed(history) if not x.startswith(USER)), "")
        if self._record_after and coach:
            lines = [*lines, f"（管家上一句的结尾，只用来看懂他这句在回答什么）…{coach[-200:]}"]
        return lines

    async def _settle_state(self, user_id: str, text: str, run: dict[str, Any], context: Sequence[str] = ()) -> None:
        """作答后写他这句说了自己什么（§114）：管家作答了才写，失败或走了别的路就不写，不按关键词兜底（§163）。
        §166 起作答时不给 record_state：回答发出后在后台由管家读这句话（带上前两句）再记，省作答时的一轮往返。"""
        if run.get("state_by") != "model":
            return
        if not self._record_after:
            await self._apply_said(user_id, run.get("_said_state") or {}, run)
            return
        from types import SimpleNamespace

        from ironm_agent import body_state

        stores = SimpleNamespace(illness=self._illness_store(), day=self._day_store(), pain=self._pain_store(),
                                 memory=self._memory_store())  # fmt: skip
        ill = illness_line(run.get("_ill") or [], date.today(), within=14)
        lines = [*([f"前面：他最近{ill}"] if ill else []), *context]  # 正在生病：他说"好多了"才对得上
        if (llm := await self._quiet_llm(user_id)) is None:  # 用他自己的模型，没填不读（§167）
            return
        got = await body_state.read_text(user_id, text, date.today(), "在对话里", stores, llm, context=lines)
        if got is not None and (got.day or got.pain or got.illness):
            await self._coach(user_id, "说了今天的状态", True)  # 首页今天的版本跟着变

    async def _apply_said(self, user_id: str, told: Mapping[str, Any], run: dict[str, Any]) -> None:
        """管家交的他这句说了自己什么：写生病记录、今日状态、说疼记录（§163：只按交的写，字段不对的跳过）。"""
        from ironm_agent import body_state

        got = await body_state.apply(user_id, told, illness=self._illness_store(), days=self._day_store(),
                                     pain=self._pain_store(), memory=self._memory_store(),
                                     at=run.get("_at") or datetime.now(UTC))  # fmt: skip
        if got.illness:
            run["illness"] = f"said:{got.illness}"
        if got.day:
            run["day_noted"] = got.day
        if got.pain:
            run["pain_parts"] = len(got.pain)
        if got.day or got.pain or got.illness:
            await self._coach(user_id, "说了今天的状态", True)  # 首页今天的版本跟着变

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

    async def _sore(self, user_id: str, today: date, memory: Sequence[Any]) -> list[str]:
        """最近 3 天说过疼（好了之后说的）的部位：排计划时和记着的伤病一样避开（§158）；读不到当作没有。"""
        from ironm_agent.body_now import SORE_DAYS, sore

        try:
            pains = await self._pain_store().since(user_id, today - timedelta(days=SORE_DAYS))
        except Exception as e:
            _log.warning("pain unavailable: error_type=%s", type(e).__name__)
            return []
        return sore(pains, memory, today)

    async def _today_lines(
        self,
        user_id: str,
        plan: Plan | None,
        today: date,
        state: DayState | None,
        ill: list[Episode],
        memory: Sequence[Any] = (),
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
        from ironm_agent.body_now import fresh

        pains = fresh(pains, memory)  # 说好了的那处，之前的疼不进"今天"（§158）
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
                if (llm := await self._quiet_llm(user_id)) is None:  # 用他自己的模型，没填不提取（§167）
                    return
                out = await extract(llm, items, text, answer, context, held)
                await store.apply(user_id, out.changes)  # 生病记录不再从记忆里补记（§163）
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

    def _timeline_tool(self, user_id: str, raw: Any, today: date) -> dict[str, Any]:
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
        run["_t0"] = start
        llm: Any = _NoModel()
        problem = ""  # 没有可用的模型时这一轮怎么说（§167）
        try:
            own = await self._own_llm(user_id)
            if own is None:
                problem = NO_MODEL_CHAT
            else:
                llm = own
        except Exception as e:  # 读不到他的模型设置：如实说，不当成没填，也不换成别的模型
            _log.warning("user model unavailable: error_type=%s", type(e).__name__)
            problem = SETTINGS_DOWN
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
            if problem and assess(text).level == "none":  # 急症、红旗照样走下去，给规则里的固定安全回答
                run["path"] = "no_model"
                yield text_block(problem)
                return
            async for block in self._turn(user_id, session_id, text, llm, run, said, file_list):
                yield block
            run["state_by"] = "model" if run.get("_judged_state") else "keyword"
            self._later(user_id, self._settle_state(user_id, text, run, said.get("history") or []))  # §114、§166
            if "answer" in said and self._remember_on:
                if said.get("remembered"):  # 单 Agent 这一轮已经当场记了（§68）
                    run["memory_extract"] = "agent"
                else:  # 不先用关键词判断，后台兜底提取一次（§68）
                    self._later(
                        user_id,
                        self._remember(user_id, text, said["answer"], self._memory_context(said["history"])),
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
            done = run["_desk"].done_note() if run.get("_desk") is not None else ""
            yield {"type": "error", "message": "\n\n".join(x for x in (FAILED, done) if x)}
        finally:
            # 这一轮存下、卡片却没发出去的预览（出错、断开、被取消）作废（§120）；放进后台，取消时也能跑完
            if (desk := run.pop("_desk", None)) is not None and desk.drafts:
                self._later(user_id, self._drop_drafts(user_id, desk.drafts))
            run["ms"] = int((time.perf_counter() - start) * 1000)
            run["model_calls"] = len(llm.calls)
            run["model_failures"] = sum(1 for c in llm.calls if not c.ok)
            # 每次调用模型各用了多少毫秒、输入多少、命中缓存多少（§165）
            run["calls_ms"] = [f"{c.stage}:{c.ms}" for c in llm.calls]
            run["prompt_tokens"] = sum(c.prompt for c in llm.calls)
            run["cache_hit"] = sum(c.cached for c in llm.calls)
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
        waited = time.perf_counter()
        try:
            routed = await routing
        except Exception as e:  # 路由出错：退回按关键词
            _log.warning("skill route failed: error_type=%s", type(e).__name__)
            routed = None
        run["route_wait_ms"] = int((time.perf_counter() - waited) * 1000)  # 等选规程等了多久（§165）
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
        sick_now = bool(active_illness(run.get("_ill") or [], snapshot.today))

        async def everything() -> list[Any]:
            """查旧记忆、时间线用到时才取全部（含归档了的，§157），照样去掉没生病时的生病内容（复核 11-04）。"""
            rows = await self._memory_store().items(user_id, current_only=False)
            return list(rows) if sick_now else [
                x for x in rows if not (x.category in ("event", "advice") and mentions(x.content))
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
            extra={**EXTRA_TOOLS, RECALL: (RECALL_SCHEMA, recall_tool(raw, snapshot.today, load=everything)),
                   **self._web_tools(snapshot.today), **self._timeline_tool(user_id, everything, snapshot.today)},
        )  # fmt: skip
        if checked is not None:
            toolbox.evidence.absorb(checked)
        personal = await basics
        run["basics"] = len(personal.lines)
        known = lay.handles
        remembering = self._remember_on and not await self._paused(user_id)  # 暂停记忆不给（§145）
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
                                  confirmed=confirmed, merge=bool(history), blocked=blocked is not None,
                                  snapshot=snapshot, known=known, remembering=remembering,
                                  history=history),
            has_plan=plan is not None, must_plan=confirmed_now and replying and blocked is None,
        )  # fmt: skip
        if remembering:  # "记下了"算不算做了：回答写完后核对，通过的长期记忆才算（复核 11-03）
            desk.memory_ok = lambda answer: _memory_holds(
                desk.memory, known, text, answer, snapshot.today
            )
        toolbox.actions = desk
        run["_desk"] = desk  # 这一轮出了异常时作废它存下的预览（generate_response 里）
        if "_t0" in run:  # 作答前的准备（读数据、选规程……）用了多少毫秒（§165）
            run["pre_ms"] = int((time.perf_counter() - run["_t0"]) * 1000)
        steps: asyncio.Queue[tuple[str, str, str, bool | None]] = asyncio.Queue()
        toolbox.progress = lambda *e: steps.put_nowait(e)  # 每开始、做完一步告诉页面（§165）
        answering = asyncio.create_task(respond(
            text, history, concerns_of(text), toolbox, llm, personal, recall, case=case, skills=loaded,
            note="" if chatting else note, with_case=not chatting,
            has_plan=plan is not None, confirmed=confirmed, just_asked=confirmed_now,
            today=snapshot.today, training=on_training, record_after=self._record_after,
            images=[x.part() for x in files.images], known=known, memory_block=memory_block,
        ))  # fmt: skip
        try:
            async for block in _steps_until(answering, steps):
                yield block
        finally:
            if not answering.done():  # 他断开了：这一轮不再往下答
                answering.cancel()
        c = answering.result()
        yield finished("agent", consultation_summary(c), ok=c.status != "failed")
        run["_judged_state"] = c.status != "failed"  # 作答了：没调 record_state 就是没说（§122）
        run["_said_state"] = dict(desk.said)
        if desk.memory and self._remember_on:  # 这一轮调 remember 交的：核对后当场写入（§68、§145）
            said["remembered"] = await self._remember_now(
                user_id, text, c.opinion.answer, desk.memory, known, run, snapshot.today
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
            yield text_block("\n\n".join(x for x in (fixed_risk, desk.done_note()) if x) if must_block
                             else "\n\n".join(x for x in (refusal_fixed, NO_ANSWER, desk.done_note()) if x))  # fmt: skip
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
            yield text_block("\n\n".join(x for x in (fixed_risk, desk.done_note()) if x))
            return
        if action == "new_plan":
            # 要新计划、本会话还没确认条件：由它用自己的话列出条件请他确认（§55、§86），不出预览；
            # 开头那段没有"排新计划前先确认一下"（下一轮靠它认出问过了）时，退回系统列的五项
            # 改目标的卡片照出（§151：他说了新目标，同一轮又要先确认排计划的条件，两件事都要给他）
            goal_draft = desk.goal.draft if desk.goal is not None else ""
            await self._drop_drafts(user_id, [d for d in desk.drafts if d != goal_draft])
            ask = own if asks_terms else confirm_ask(terms)
            run.update(
                path="clarify", missing=["confirm"], clarify_by="model" if asks_terms else "fixed"
            )
            said["answer"] = ask
            note = CONFIRM_NOTE["goal"] if desk.goal is not None else ""
            yield text_block("\n\n".join(x for x in (refusal_fixed, ask, note) if x))
            for block in desk.goal.cards if desk.goal is not None else ():
                yield block
            run.pop("_desk", None)  # 卡片发出去了：后面再出什么事也不作废它
            return
        run["task"] = "plan" if desk.plan is not None else "log" if desk.logs else None
        run["_tail"] = ""  # 风险提醒、生病追问已经作为要求交给它（§86），不再拼在末尾

        def rules(answer: str) -> list[Violation]:
            return check_constraints(answer, ctx)

        def mark(answer: str) -> str:
            return annotate(answer, ctx)

        composed = await revise(c, text, llm, constraints=rules, memory=recall, annotate=mark)
        run.update(constraints=list(composed.violations), constraint_fixed=composed.fixed)
        run["_compose"] = {"checks": list(composed.checks), "repaired": composed.repaired}
        if must_block:  # 危急指标：查它说到了先别运动、尽快就医，没给训练安排（§86 需求 2）
            lack = missing(composed.text, RISK_NEEDS)
            run["risk_by"] = "fixed" if lack else "model"
            if lack:
                await self._drop_drafts(user_id, desk.drafts)
                run["path"] = "risk"
                said["answer"] = ""
                yield text_block("\n\n".join(x for x in (fixed_risk, desk.done_note()) if x))
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
        if not (kinds or ask_ill or cards or pain_parts(text) or detect(text) or sick_now):
            from ironm_agent.memory_layers import stale_question

            still, due_ask = stale_question(lay, composed.text)  # 很久没确认的那条：管家没问就补一句（§160）
            if still and due_ask is not None:
                composed = replace(composed, text=composed.text.rstrip() + "\n\n" + still)
                run["stale_ask"] = "fixed"
                try:  # 补问过了：这条该问的结束，他不答也不再每轮补（30 天后到期再问，复核 11-04）
                    await self._memory_store().apply(user_id, [Change("status", id=due_ask.id, status="resolved")])
                except Exception as e:
                    _log.warning("stale ask close failed: error_type=%s", type(e).__name__)
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
            draft = await self._training_store().pending_plan(user_id, skip_source="checkup")
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
        snapshot: Snapshot | None = None,
        known: Mapping[str, Any] | None = None,
        remembering: bool = False,
        history: Sequence[str] = (),
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
            if not args.get("plan") and args.get("template"):  # 照方案库草稿交：代码套改法（§165）
                new, why = self._from_template(desk, args, tools)
            else:
                new, why = parse_plan(args.get("plan"))
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

        goal = {"kcal": _metric_value(snapshot, "kcal_target")}  # 这一轮里调过热量，后面按新目标算

        async def record_state(desk: Desk, args: Mapping[str, Any]) -> Outcome:
            told = {k: v for k, v in args.items() if k in STATE_FIELDS and v not in (None, "", [])}
            if not told:
                return Outcome(False, "没写他说了什么状态；他没说就不用调用。", "format")
            desk.said.update(told)  # 作答后按原来的规则写（§46、§54、§114）
            return Outcome(True, "收到，作答后写进今天的状态。", kind="state", what="state")

        async def log_body(desk: Desk, args: Mapping[str, Any]) -> Outcome:
            from ironm_agent.memory_extract import digits
            from ironm_agent.readings import KINDS, OutOfRange, check

            kind, said = str(args.get("kind") or ""), args.get("value")
            if (
                kind not in BODY_KINDS
                or not isinstance(said, int | float)
                or isinstance(said, bool)
            ):
                return Outcome(
                    False, "要写哪一项（体重、体脂率、腰围、静息心率、血压）和他说的数。", "format"
                )
            raw = f"{float(said):g}"
            if raw not in digits(
                text, chinese=True
            ):  # 数只能是他这句话里说的（说斤就写斤的那个数）
                return Outcome(False, "这个数不在他这句话里，没记：写他原话里的数，说的是斤就写斤的数、"
                               "unit 写斤，由系统换算；他没说具体的数就问他。", "number")  # fmt: skip
            jin = kind == "weight" and _in_jin(raw, args.get("unit"), text)
            if jin is None:
                return Outcome(
                    False,
                    "他这句话里斤和公斤都有，看不出这个数是哪个单位：问他，或者 unit 写清楚。",
                    "unit",
                )
            value = float(said) / 2 if jin else float(said)
            day = today
            if args.get("day"):
                try:
                    day = date.fromisoformat(str(args["day"]))
                except ValueError:
                    return Outcome(False, "日期写成 YYYY-MM-DD（今天就不写），没记。", "day")
            if day > today or (today - day).days > 30:
                return Outcome(False, "日期只能是今天或 30 天以内，没记。", "day")
            try:
                k = check(kind, value)
            except OutOfRange as e:
                return Outcome(False, f"没记：{e}，问他是不是说错了。", "range")
            store = self._readings_store()
            try:  # 同一天记过同样的数：不重复写（数据库那边也挡，这里先看一眼，两种存储一样）
                seen = await store.recent(user_id, kind, limit=20)
            except Exception:
                seen = []
            same_day = [r for r in seen if r.get("day") == day.isoformat()]
            if any(float(r.get("value") or 0) == value for r in same_day):
                return Outcome(
                    False, f"{k.title} {value:g} {k.shown}这天已经记过，没重复记。", "dup"
                )
            if (
                await store.add(user_id, kind, value, day) < 1
            ):  # 健康记录里一天一项只留一个（同数据页）
                had = f"（{float(same_day[0].get('value') or 0):g} {k.shown}）" if same_day else ""
                return Outcome(False, f"这天已经记过一个{k.title}{had}，一天只记一个，这个没记上；"
                               "他要改就在数据页改那一条。", "dup")  # fmt: skip
            self._later(user_id, self._coach(user_id, "记数据", True))
            when = "" if day == today else f"（{day.month}月{day.day}日）"
            said_as = f"（他说的是 {raw} 斤）" if jin else ""
            return Outcome(True, f"已记下{when}：{KINDS[kind].title} {value:g} {k.shown}{said_as}"
                           "（数据页能改、删）。", kind="saved", what="body",
                           note=f"记下了{when}{KINDS[kind].title} {value:g} {k.shown}")  # fmt: skip

        async def log_meal(desk: Desk, args: Mapping[str, Any]) -> Outcome:
            from ironm_agent.meals import Macros, food_line, meal_from, totals

            kind = str(args.get("kind") or "")
            if kind not in MEAL_KINDS:
                return Outcome(
                    False, "要写哪一餐（早餐、午餐、晚餐、加餐、夜宵、练前、练后）。", "format"
                )
            foods = [f for f in args.get("foods") or [] if isinstance(f, Mapping)]
            if len(foods) > MAX_FOODS:
                return Outcome(False, f"一餐最多记 {MAX_FOODS} 样，合并一下再交。", "format")
            lines, missed, bad, by_portion = [], [], [], []
            for f in foods:
                name, grams = str(f.get("name") or "").strip()[:30], f.get("grams")
                n = f.get("portions")
                if not isinstance(grams, int | float) and isinstance(n, int | float) and 0 < float(n) <= 10:
                    from ironm_agent.foods import find as find_food

                    known = find_food(name)  # 说的是几碗、几个：按食物库里一份的克数（复核 11-05）
                    if known is None:
                        bad.append(f"{name}（库里没有，写克数）")
                        continue
                    grams = float(n) * known.unit_g
                    by_portion.append(f"{name} {float(n):g} {known.unit}按 {round(grams)} 克")
                if not name or not isinstance(grams, int | float) or not 0 < float(grams) <= 3000:
                    bad.append(name or "没写名字的")
                    continue
                est = None
                if isinstance(f.get("per100"), Mapping):
                    try:
                        est = Macros.model_validate(f["per100"])
                    except Exception:
                        bad.append(f"{name}（每 100 克估值要写全 kcal、protein_g、carbs_g、fat_g）")
                        continue
                try:
                    lines.append(
                        food_line(name, float(grams), str(f.get("oil") or "正常"), est100=est)
                    )
                except KeyError:
                    missed.append(name)
                except Exception:  # 克数乘估值超出合理范围
                    bad.append(f"{name}（份量或估值不合理）")
            if not lines:
                why = "；".join(x for x in (f"库里没有{'、'.join(missed)}，又没给每 100 克的估值" if missed else "",
                                         f"写得不对：{'、'.join(bad)}" if bad else "") if x) or "没写吃了什么、多少克"  # fmt: skip
                return Outcome(False, f"没记：{why}。补上再交。", "format")
            title = str(args.get("name") or "").strip() or "、".join(x.name for x in lines)
            meal = meal_from(kind, title, lines, estimated=True, note="对话里记的，按食物库算")  # type: ignore[arg-type]
            store = self._meals_store()
            row = await store.add(user_id, today, meal)
            for old in await store.day(user_id, today):  # 每种餐每天只留一份（§43，同饮食页）
                if old.id != row.id and old.meal.kind == meal.kind:
                    await store.delete(user_id, old.id)
            day_total = totals(await store.day(user_id, today)).kcal
            self._later(user_id, self._coach(user_id, "记饮食", True))
            target = goal["kcal"]
            left = (
                f"，目标约 {round(target)}，还能吃约 {max(0, round(target - day_total))} 千卡"
                if target
                else ""
            )
            skipped = "；".join(x for x in (f"{'、'.join(missed)}库里没有又没给估值" if missed else "",
                                            f"{'、'.join(bad)}没记" if bad else "") if x)  # fmt: skip
            portions = f"（{'、'.join(by_portion)}）" if by_portion else ""
            return Outcome(True, f"已记下{kind}：{meal.name}{portions}，约 {round(meal.macros.kcal)} 千卡、蛋白质 "
                           f"{round(meal.macros.protein_g)} 克（今天的{kind}只留这一份）；今天一共约 "
                           f"{round(day_total)} 千卡{left}{'；' + skipped + '，没算进去' if skipped else ''}"
                           "（饮食页能改份量、删掉）。", kind="saved", what="meal",
                           note=f"记下了{kind}：{meal.name}（约 {round(meal.macros.kcal)} 千卡）",
                           calc=f"{kind}{meal.name}按食物库算约 {round(meal.macros.kcal)} 千卡、蛋白质 "
                                f"{round(meal.macros.protein_g)} 克；今天一共约 {round(day_total)} 千卡{left}")  # fmt: skip

        async def adjust_today(desk: Desk, args: Mapping[str, Any]) -> Outcome:
            from ironm_agent.plan_edit import edit as edit_today
            from ironm_agent.plan_edit import today_session
            from ironm_agent.training import PlanEdit

            session = current.session_on(today) if current is not None else None
            if current is None or session is None or tools is None:
                why = "他还没有训练计划" if current is None else "今天按计划不练"
                return Outcome(False, f"没改：{why}，没有今天这一次可改。", "no_session")
            days = self._day_store()
            try:
                state = await days.get(user_id, today)
            except Exception:
                state = None
            before = list(state.edits) if state is not None else []
            cur = Plan(
                title=current.title, days_per_week=1, sessions=[today_session(session, before)]
            )
            edits: list[PlanEdit] = []
            for c in args.get("changes") or []:
                if isinstance(c, Mapping) and c.get("kind") in ("swap", "edit", "remove"):
                    try:
                        edits.append(PlanEdit.model_validate({k: c[k] for k in
                                     ("kind", "exercise", "to", "sets", "reps") if c.get(k) not in (None, "")}))  # fmt: skip
                    except Exception:
                        return Outcome(
                            False,
                            "改法没写对：每条写 kind（swap/edit/remove）和今天那一次里的动作名。",
                            "format",
                        )
            ratio = args.get("ratio")
            scaling = isinstance(ratio, int | float) and not isinstance(ratio, bool)
            if scaling and not 0.5 <= float(ratio) <= 0.9:  # type: ignore[arg-type]
                return Outcome(False, "整体按几成练要在 0.5–0.9 之间。", "format")
            if not edits and not scaling:
                return Outcome(
                    False, "没写要怎么改（换动作、改组次、去掉，或者整体按几成练）。", "format"
                )
            applied: list[PlanEdit] = []
            lines: list[str] = []
            notes: list[str] = []
            skipped: list[str] = []
            warnings: list[str] = []
            for e in (
                edits
            ):  # 一条一条套：只存真正套上的；被换成替代动作的按实际换上的存（独立审查 11-03）
                had = {x.exercise for x in cur.sessions[0].items}
                got = edit_today(cur, session.day, [e], equipment=tools.equipment, injured=tools.injured,
                                 special=tools.special)  # fmt: skip
                if not got.lines:
                    skipped += got.skipped or [f"{e.exercise}没改成"]
                    continue
                if got.problems:
                    skipped.append(
                        f"{e.exercise}这样改有问题：" + "；".join(plain(x) for x in got.problems)
                    )
                    continue
                actual = e
                if e.kind == "swap":
                    new = [x.exercise for x in got.plan.sessions[0].items if x.exercise not in had]
                    if new and new[0] != e.to:
                        actual = e.model_copy(update={"to": new[0]})
                applied.append(
                    actual.model_copy(update={"line": "；".join([*got.lines, *got.notes])[:120]})
                )
                lines += got.lines
                notes += got.notes
                warnings += got.warnings
                cur = got.plan
            if (
                scaling
            ):  # 按几成练在具体改法之后、按改完的算；他明说了组数的动作不再按比例减（复核 11-03）
                named = {e.to or e.exercise for e in applied if e.kind == "edit" and e.sets}
                cut = 0
                for x in cur.sessions[0].items:
                    n = max(1, int(x.sets * float(ratio) + 0.5))  # type: ignore[arg-type]  # 同计划减量的取整（§45）
                    if x.exercise in named or n >= x.sets:
                        continue
                    e = PlanEdit(kind="edit", exercise=x.exercise, sets=n)
                    got = edit_today(cur, session.day, [e], equipment=tools.equipment, injured=tools.injured,
                                     special=tools.special)  # fmt: skip
                    if got.lines and not got.problems:
                        applied.append(e.model_copy(update={"line": "；".join(got.lines)[:120]}))
                        lines += got.lines
                        cur = got.plan
                        cut += 1
                if not cut:
                    skipped.append("按这个比例组数没有变化（组数少的动作至少留 1 组）")
            if not applied:
                return Outcome(
                    False, "没改成：" + "；".join(skipped) + "。照这个跟他说。", "rejected"
                )
            await days.set_edits(user_id, today, [*before, *applied])
            self._later(user_id, self._coach(user_id, "只改今天", True))
            run["today_edits"] = len(applied)
            parts = ["已改好今天这一次：" + "；".join(lines)]
            if notes:
                parts.append("另外：" + "；".join(notes))
            if skipped:
                parts.append("没改的：" + "；".join(skipped))
            if warnings:
                parts.append("提醒：" + "；".join(plain(x) for x in warnings))
            return Outcome(True, "。".join(parts) + "（原计划不变，计划页能恢复今天原样）。", kind="changed",
                           what="today", note="今天这一次改了：" + "；".join(lines))  # fmt: skip

        async def kcal_change(desk: Desk, args: Mapping[str, Any]) -> Outcome:
            from ironm_agent.diet_adjust import _apply as within_limits
            from ironm_agent.metrics import KcalAdjust
            from ironm_agent.special import MINOR, PREGNANCY

            delta = args.get("delta")
            target, bmr = goal["kcal"], _metric_value(snapshot, "bmr")
            if not isinstance(delta, int | float) or isinstance(delta, bool) or not delta:
                return Outcome(False, "要写每天多吃（正数）或少吃（负数）多少千卡。", "format")
            if snapshot is None or target is None or bmr is None:
                return Outcome(
                    False, "他的热量目标还算不出来（缺身高、体重、年龄或目标），没调。", "no_target"
                )
            if delta < 0 and tools is not None and tools.special & {MINOR, PREGNANCY}:
                return Outcome(False, "没调：18 岁以下、孕期不在对话里减热量，跟他说请医生或营养师定（§90 规程）。",
                               "special")  # fmt: skip
            diet = self._diet_store()
            reason = str(args.get("reason") or "你要求的").strip()[:60]
            prop, why = within_limits(round(float(delta)), reason, "对话里调的", target, bmr,
                                      snapshot.profile, await diet.current(user_id))  # fmt: skip
            if prop is None:
                return Outcome(False, f"没调：{why}", "limit")
            await diet.apply(user_id, KcalAdjust(prop.total, today, reason))
            goal["kcal"] = float(prop.after)
            self._later(user_id, self._coach(user_id, "调热量", True))
            note = "" if prop.delta == round(float(delta)) else "（按上下限调到这里）"
            return Outcome(True, f"已调好：每日热量目标 {prop.before} → {prop.after} 千卡{note}"
                           "（饮食页能撤销）。", kind="changed", what="kcal",
                           note=f"每日热量目标调到 {prop.after} 千卡",
                           calc=f"每日热量目标 {prop.before} → {prop.after} 千卡{note}")  # fmt: skip

        async def remember(desk: Desk, args: Mapping[str, Any]) -> Outcome:
            """记忆（§145）：按 §68 的规则先核一遍，没通过的退回原因；跟进类的原话可能出自管家自己的回答，
            先收下。回答写完后再完整核对一次才写入（_remember_now）。"""
            from ironm_agent.memory_extract import validate

            raw = args.get("items")
            ops = [dict(x) for x in raw if isinstance(x, Mapping)] if isinstance(raw, list) else []
            if not ops:
                return Outcome(
                    False,
                    "要写 items：每条一件他说了的事（op、category、content、quote）。",
                    "format",
                )
            room = MEMORY_CAP - len(desk.memory)
            if room <= 0:
                return Outcome(False, f"这一轮已经交了 {MEMORY_CAP} 条，够了，不用再交。", "memory")
            kept, why, again = [], [], 0
            for op in ops[:room]:
                ok, bad = validate({"ops": [op]}, known or {}, text, "", today=today)
                target = (known or {}).get(str(op.get("target") or ""))
                cat = str(op.get("category") or getattr(target, "category", ""))
                if ok or cat == "followup":  # 跟进（含按编号结束的）原话可能在回答里：先收下
                    kept.append(op)
                    again += op.get("op") == "add" and all(o.op == "confirm" for o in ok) and bool(ok)
                elif bad:
                    why += bad[:1]
            if not kept and not why:  # 已经记着的：validate 静默跳过（复核 11-03）
                return Outcome(False, "这些已经记着了，不用再交。", "memory")
            desk.memory += kept
            if why:  # 运行记录只记条数（§68）
                run["memory_tool_rejected"] = int(run.get("memory_tool_rejected") or 0) + len(why)
            back = f"没记：{'；'.join(dict.fromkeys(why))}。改了再交，或者不记。" if why else ""
            if not kept:
                return Outcome(False, back, "memory")
            if again == len(kept):  # 原样又说了一遍：算他确认了那条（§154）
                return Outcome(True, "这些已经记着了，算他又确认了一次（更新日期改成今天），不用再交。",
                               kind="memory", what="memory")  # fmt: skip
            return Outcome(
                True,
                f"收到 {len(kept)} 条，回答写完后核对写入。{back}",
                kind="memory",
                what="memory",
            )

        async def set_goal(desk: Desk, args: Mapping[str, Any]) -> Outcome:
            """改正式目标（§151）：类型、目标体重和日期要是他说的；出改目标的预览卡片，他确认才改。"""
            # 分几轮说的（"想减到 65 公斤"→"哪天？"→"半年吧"）、答应管家给的方案（"可以"）：
            # 他前几句和管家上一句也算原话（复核 11-03）；确认卡片前他还能看清
            said = "\n".join([text, *user_lines(list(history))[-3:], *[x for x in history if x.startswith(COACH)][-1:]])
            return await self._goal_preview(user_id, said, today, snapshot, args, store)

        async def temp_change(desk: Desk, args: Mapping[str, Any]) -> Outcome:
            """这几天临时这样练（§163 需求 2）：套到当前计划上、检查，出临时调整的预览卡片，他确认才生效。"""
            if current is None or tools is None:
                return Outcome(False, "他还没有训练计划，没有可以临时调整的；要先排计划。", "format")
            return await self._temp_preview(user_id, current, args, ctx, tools, run, today, store)

        handlers: dict[str, Handler] = {
            LOG_WORKOUT: log_workout, RECORD_STATE: record_state, LOG_BODY: log_body,
            LOG_MEAL: log_meal, KCAL_CHANGE: kcal_change, SET_GOAL: set_goal,
        }  # fmt: skip
        if remembering:  # 暂停记忆、系统拼出来的问法：不给（§145）
            handlers[REMEMBER] = remember
        if not blocked:  # 危急情况：不给训练安排（§5），记录和饮食照旧
            handlers[NEW_PLAN] = new_plan
            handlers[ADJUST_TODAY] = adjust_today
            if current is not None:
                handlers[PLAN_EDIT] = edit
                handlers[TEMP_CHANGE] = temp_change
        return handlers

    async def _temp_preview(
        self, user_id: str, current: Plan, args: Mapping[str, Any], ctx: Context, tools: ToolContext,
        run: dict[str, Any], today: date, store: Any,
    ) -> Outcome:  # fmt: skip
        """临时调整（§163 需求 2）：日期、改法核对后套到当前计划上、检查新带来的问题，存成预览。
        不按时长修剪：生效时也不修剪，预览要和生效的一样（复核 11-05）。检查按叠上重叠的临时调整后的那版。"""
        from ironm_agent import plan_layers
        from ironm_agent.plan_ops import Conflict, apply, parse_ops

        try:
            start = date.fromisoformat(str(args.get("start") or ""))
            end = date.fromisoformat(str(args.get("end") or ""))
        except ValueError:
            return Outcome(False, "start、end 写成 YYYY-MM-DD。", "format")
        if start < today or end < start or (end - start).days >= plan_layers.MAX_DAYS:
            return Outcome(False, f"日期要从今天或以后开始、结束不早于开始、最长 {plan_layers.MAX_DAYS} 天；"
                           "更长的是改计划本身，用 propose_plan_edit。", "format")  # fmt: skip
        ops = parse_ops(args.get("ops"))
        if not ops:
            return Outcome(False, "ops 要是改法列表，写法同 propose_plan_edit。", "format")
        base = plan_layers.stacked(current, await plan_layers.load(store, user_id), start, end)
        try:
            applied = apply(current, ops, equipment=tools.equipment, injured=tools.injured)
        except Conflict as e:
            return Outcome(False, f"改法互相矛盾：{e}。问他想怎么改。", "conflict")
        try:
            layered = apply(base, ops, equipment=tools.equipment, injured=tools.injured).plan
        except Conflict as e:
            return Outcome(False, f"和他已经确认的临时调整冲突：{e}。先问他那份要不要撤销。", "conflict")
        if not applied.done:
            return Outcome(False, "一条都没改成：" + "；".join(applied.skipped) + "。看清计划里那几天的动作再交。", "rejected")

        def review(p: Plan) -> tuple[str, ...]:
            return check_plan(p, current=base, goal=tools.goal, injured=tools.injured,
                              equipment=tools.equipment, special=tools.special).problems  # fmt: skip

        had = {_no_day(x) for x in review(base)}
        left = [x for x in review(layered) if _no_day(x) not in had]
        if left:
            run["plan_check"] = "failed"
            return Outcome(False, "这样改会有问题：" + "；".join(left) + "。改了再交。", "check")
        why = str(args.get("why") or "")[:60]
        stored = await store.plan(user_id)
        content = plan_layers.content(start, end, why, applied, applied.lines, stored.line_id if stored else "")
        draft = await store.add_draft(user_id, "temp", content)
        run["preview"] = "temp"
        return Outcome(True, "已出临时调整的预览卡片，等他确认（确认前计划没改，到期自动回到原计划）。", kind="temp",
                       cards=tuple(temp_card(draft, content)), draft=draft.id, what="temp")  # fmt: skip

    @staticmethod
    def _from_template(desk: Desk, args: Mapping[str, Any], tools: ToolContext | None) -> tuple[Plan | None, str]:
        """照方案库草稿交的新计划（§165）：这一轮 plan_templates 给过的那份草稿，套上改法。"""
        from ironm_agent.plan_ops import Conflict, apply, parse_ops

        base = desk.template_plans.get(str(args.get("template") or ""))
        if base is None:
            return None, "这一轮方案库没给过这个方案编号的草稿：先调 plan_templates，或者交完整的 plan"
        raw = args.get("ops")
        if not raw:
            return base, ""
        ops = parse_ops(raw)
        if not ops:
            return None, "ops 要是改法列表，写法同 propose_plan_edit"
        try:
            got = apply(base, ops, equipment=tools.equipment if tools else None,
                        injured=tools.injured if tools else ())  # fmt: skip
        except Conflict as e:
            return None, f"改法互相矛盾：{e}"
        if not got.done or got.skipped:  # 有没套上的：不悄悄丢掉，告诉它哪几条，改了再交（审查 11-05）
            return None, "这几条改法没套上：" + "；".join(got.skipped or ["一条都没套上"])
        return got.plan, ""

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
                # 每日复查提的预览不是这段对话给的：取的时候就跳过（不压住这段对话更早的预览，复核 11-03）
                prior = await store.pending_plan(user_id, skip_source="checkup")
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
                      for d in review.done if not d.undone and d.type != "propose"]  # fmt: skip
            lines += [(f"管家今天提了改计划、还没确认：{d.title}（原因：{d.why}）", f"{d.title}。原因：{d.why}")
                      for d in review.done if not d.undone and d.type == "propose"]  # fmt: skip
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
        from ironm_agent.plan_layers import load as load_temps

        lines += [f"临时调整（他确认过的，到期回到原计划）：{t.line()}"
                  for t in await load_temps(self._training_store(), user_id) if t.end >= snapshot.today]  # fmt: skip
        recovering = recovering_days(ill, snapshot.today)  # 生病期间的组次不触发减重量（§46）
        steady = [x for x in logs if x.day not in recovering]
        # 生病只交事实（哪天说的什么、好没好），今天怎么练由管家定，代码不再算"休息、轻松、七成"（§163）
        state = illness_line(ill, snapshot.today, within=14).removeprefix("生病：")
        signal: tuple[Literal["poor", "fair"], str] | None = ("fair", state) if state else None
        day = (run or {}).get("_day")
        at = (run or {}).get("_at")
        body = await self._memory_items(user_id)  # 没截过的（截过的可能丢了"已好"那条，复核 11-04）
        today_lines = await self._today_lines(user_id, plan, snapshot.today, day, ill, body)
        sore_parts = await self._sore(user_id, snapshot.today, body)
        found, insight_lines = await self._insights(user_id, snapshot, logs, ill, recall)
        if run is not None:
            run["_found"] = found
        coach = await self._coach_state(user_id)  # 管家练完后定的下次目标（§132）
        decided = coach.decided() if coach is not None else None
        target = await self._target(user_id, snapshot)  # 目标体重和日期：档案里目标一行带上（§151）
        case = build_case(
            snapshot, recall, text, plan=lines + target_lines(plan, steady, snapshot.today, decided),
            illness=signal, day=today_lines, earlier=day_signals(day, before=at),
            insights=insight_lines, target=target, sore=sore_parts,
        )  # fmt: skip
        current = await wx if wx is not None else None
        if current is not None:
            case = replace(case, weather=_weather_case(current, plan, snapshot.today))
        if run is not None:
            run["weather"] = current is not None
        return Prepared(snapshot, plan, case)

    def _answer(
        self, composed: Composed, prefix: str, run: dict[str, Any], said: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """回答正文与可展开的“依据与来源”。"""
        run.update(path="answer", rewrites=composed.rewrites, kb=[e.id for e in composed.entries])
        blocks = []
        said["answer"] = answer_text(composed)
        blocks.append(
            text_block(answer_text(composed, prefix=prefix, suffix=run.get("_tail") or ""))
        )
        sources = sources_text(composed)
        if sources:  # 出处不写进正文，放进可展开的“依据与来源”
            blocks.append(started(SOURCES_ID, SOURCES_NAME, "这条回答用到的资料、计算和你的数据"))
            blocks.append(finished(SOURCES_ID, sources))
        return blocks
