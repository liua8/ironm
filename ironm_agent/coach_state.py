"""管家的当前方案与调整经历（spec [2026-10-23] §23 第 1 步）。

当前方案：管家此刻打算怎么带这个人——今天的版本、每个动作的下次目标、每日热量与蛋白质、目标进度与复测、
正在生效的提醒、待确认的方案。每一项写明原因和依据，由已有的规则计算（不调用模型）。
每次重新评估都和上一版比，改了什么写进调整经历。有新情况（打卡、记饮食、说疼、改目标、确认或撤销方案）
时重新评估；每天第一次打开 App 或提问时评估一次，同一天没有新情况不重复算。
方案和调整经历加密存储；日志只记条数，不记内容。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
import weakref
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from ironm_agent.casefile import Snapshot
from ironm_agent.metrics import KcalAdjust
from ironm_agent.training import Plan, WorkoutLog, weekday_name

_log = logging.getLogger("ironm_agent.coach_state")

type Kind = Literal[
    "today", "weather", "target", "kcal", "goal", "retest", "alert", "proposal", "review"
]  # review：管家复盘里模型决定的调整（§85）
type Action = Literal["auto", "confirm", "info"]  # 自动生效 / 要用户确认 / 只提醒
type ChangeKind = Literal[
    "added", "changed", "removed", "accepted", "declined"
]  # 后两种是用户的选择

HISTORY_DAYS = 63  # 读多久的训练记录（平台期要看 9 周）


class Item(BaseModel):
    key: str  # 同一项在各版本里的编号，如 today、target:杠铃深蹲、review:kcal
    kind: Kind
    title: str  # 给人看的一句话
    why: str = ""  # 原因
    basis: str = ""  # 依据（依据库编号、规则或经验）
    action: Action = "info"
    value: dict[str, Any] = Field(default_factory=dict)  # 页面要用的结构化内容


class Choice(BaseModel):
    """用户在对话里对一条待确认调整的选择（spec [2026-10-23] §26）。"""

    decision: Literal["accept", "later"]
    title: str  # 当时这条调整的说法；调整内容变了就重新问
    day: date


class State(BaseModel):
    version: int
    day: date
    at: datetime
    reason: str  # 这次因为什么重新评估
    items: list[Item]
    seen: int = 0  # 用户在对话里看过的最新版本
    choices: dict[str, Choice] = Field(default_factory=dict)  # 每条待确认调整的选择
    report_seen: date | None = None  # 点掉的是哪一周的周报（那周的周一，§147）
    review: Review | None = None  # 今天的管家复盘（§85）
    stage_day: date | None = None  # 上次 4 周阶段小结是哪天（§89）
    week_day: date | None = None  # 上次每周复查是哪天（§163：每周叫醒管家看一次这周）
    stage_text: str = ""  # 那次的小结（对话里追问时讲）
    targets: dict[str, Any] = Field(
        default_factory=dict
    )  # 管家练完后定的下次目标（§132）：动作 → Decided

    def decided(self) -> dict[str, Any]:
        from ironm_agent.progression import Decided

        out = {}
        for k, v in self.targets.items():
            try:
                out[k] = Decided.model_validate(v)
            except ValueError:
                continue
        return out

    def item(self, key: str) -> Item | None:
        return next((x for x in self.items if x.key == key), None)


class Done(BaseModel):
    """管家复盘里一条已经生效的调整（§85）：模型决定的，代码校验后执行。"""

    key: str  # review:today / review:plan / review:kcal / review:note / review:ask
    type: Literal[
        "today", "plan", "kcal", "note", "ask", "propose"
    ]  # propose：提的改计划，等他确认（§129）
    title: str  # 给人看的一句话：改了什么
    why: str = ""  # 模型写的原因
    basis: str = ""  # 用到的事实和资料（追问依据时讲）
    expect: str = ""  # 能检查的预期（给人看的）
    check: dict[str, Any] = Field(default_factory=dict)  # 能核对的预期（expect.Check，§89）
    due: date | None = None  # 哪天核对
    value: dict[str, Any] = Field(
        default_factory=dict
    )  # today: ratio / rest；plan: draft；kcal: before、after
    undone: bool = False  # 他说了"不用这样调"


class Review(BaseModel):
    """一天一次的管家复盘（§85）。"""

    day: date
    summary: str = ""  # 模型写的一句话：今天看到的最重要的情况
    done: list[Done] = Field(default_factory=list)
    failed: bool = False  # 模型没调用成功：不调整
    checked: list[str] = Field(default_factory=list)  # 今天核对完的以前的调整（§89）
    stage: str = ""  # 今天写的 4 周阶段小结（§89）
    weekly: bool = False  # 这次是这周的每周复查（§163）
    failed_at: datetime | None = None  # 什么时候失败的：过一会儿才自动再试（复核 11-05）

    def today(self) -> Done | None:
        return next((d for d in self.done if d.type == "today" and not d.undone), None)


class Change(BaseModel):
    id: str
    at: datetime
    day: date
    version: int
    key: str
    kind: Kind
    change: ChangeKind
    before: str = ""
    after: str = ""
    why: str = ""
    basis: str = ""
    status: Action = "info"
    outcome: str = ""  # 调整后的效果：到期核对时写（§89）
    expect: str = ""  # 管家复盘写的预期（给人看的）
    check: dict[str, Any] = Field(default_factory=dict)  # 能核对的预期（expect.Check）
    due: date | None = None  # 哪天核对
    result: Literal["", "met", "missed", "unknown"] = ""  # 核对结果


# ---- 输入与规则 -------------------------------------------------------------------------------


@dataclass
class Inputs:
    snapshot: Snapshot
    plan: Plan | None = None
    since: date | None = None  # 计划从哪天开始用
    logs: list[WorkoutLog] = field(default_factory=list)
    pains: list[tuple[str, date]] = field(default_factory=list)
    pain_details: list[dict[str, Any]] = field(default_factory=list)  # 说疼的细节：左右、动作、轻重（§163）
    temps: list[Any] = field(default_factory=list)  # 他确认过的临时调整（plan_layers.Temp，§163）
    goal: Any = None  # goal.Goal
    diet: KcalAdjust | None = None
    advice: Any = None  # weather.Advice（今天的实时天气）
    forecast: tuple[Any, ...] = ()  # weather.Day：今天起 7 天的预报（spec [2026-10-23] §34）
    illness: list[Any] = field(default_factory=list)  # illness.Episode：最近的生病记录（§46）
    day: Any = None  # day_state.DayState：今日状态（§54）
    review: Review | None = None  # 今天的管家复盘（§85），模型决定的今天怎么练
    memory: list[Any] = field(default_factory=list)  # 记忆条目（§95 认特殊情况）
    seen: Any = None  # diet_adjust.Observed：按记的吃和体重变化估的实际消耗（§118）
    decided: dict[str, Any] = field(default_factory=dict)  # 管家练完后定的下次目标（§132）


@dataclass(frozen=True)
class TodayVersion:
    """今天怎么练（§97：首页"今天的版本"、管家消息、对话档案都用这一份）。"""

    status: Literal["no_plan", "rest", "sick", "review_rest", "ok"]
    title: str
    why: str = ""
    basis: str = ""
    original: dict[str, Any] | None = None
    today: dict[str, Any] | None = None
    changed: bool = False
    changes: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


def today_version(inp: Inputs, today: date) -> TodayVersion:
    """今天的版本（§163 需求 3，规则不要）：原计划先套上"只改今天"的改动（对话里管家调的、计划页他自己改的），
    再套上管家复盘对今天的决定（休息、按几成）。代码不再按生病、累、睡眠、中断、天气自己改。
    复盘还没跑完：管家正在看；复盘失败、没就今天做决定：管家出错了（可以重试）。原计划不变。"""
    from ironm_agent.today import build

    name = weekday_name(today.isoweekday())
    if inp.plan is None:
        return TodayVersion("no_plan", "还没有训练计划", why="可以让训练教练按你的目标排一份")
    from ironm_agent.plan_layers import active, plan_on

    session = (plan_on(inp.plan, inp.temps, today) or inp.plan).session_on(today)  # 套上有效的临时调整（§163）
    if session is None:
        why = "；".join(f"临时调整：{t.line()}" for t in active(inp.temps, today)) or "恢复也是训练的一部分"
        return TodayVersion("rest", f"今天（{name}）按计划休息", why=why)
    edits = list(getattr(inp.day, "edits", None) or []) if inp.day is not None else []
    if edits:  # 计划页"只改今天"、对话里管家调的只改今天（§106、§122）先套上
        from ironm_agent.plan_edit import today_session

        session = today_session(session, edits)
    original = session.model_dump(mode="json")
    review = inp.review
    told = review.today() if review is not None else None  # 管家复盘：模型决定的今天（§85）
    if told is None and review is None:
        return TodayVersion("reviewing", "管家正在看今天的情况", why="看完会告诉你今天怎么练",
                            original=original, today=original)  # fmt: skip
    if told is None and review is not None and review.failed:
        return TodayVersion("coach_error", "管家出错了，还没看今天的情况", why="可以点重试，或者直接问管家今天怎么练",
                            original=original)  # fmt: skip
    if told is not None and told.value.get("rest"):
        return TodayVersion("review_rest", f"今天休息：{told.why}", why=told.why, basis=told.basis,
                            original=original)  # fmt: skip
    if told is not None and told.value.get("ratio"):
        version = build(session, scale=float(told.value["ratio"]), scale_why=told.why)
        if version.changed:
            return TodayVersion(
                "ok", f"今天练{session.name}：" + "；".join(version.changes), why=told.why, basis=told.basis,
                original=original, today=version.session.model_dump(mode="json"), changed=True,
                changes=tuple(version.changes), reasons=(told.why,),
            )  # fmt: skip
    why = (review.summary if review is not None else "") or "管家看过今天的情况"
    if edits:
        return TodayVersion("ok", f"今天练{session.name}（只改了今天）", why=why, original=original,
                            today=original, changed=True)  # fmt: skip
    return TodayVersion("ok", f"今天练{session.name}，按原计划", why=why, original=original, today=original)


def _today_item(inp: Inputs, today: date) -> Item:
    v = today_version(inp, today)
    if v.status == "no_plan":
        return Item(key="today", kind="today", title=v.title, why=v.why)
    if v.status == "rest":
        return Item(key="today", kind="today", title=v.title, why=v.why, value={"rest": True})
    if v.status == "sick":
        return Item(key="today", kind="today", title=v.title, why=v.why, basis=v.basis,
                    action="auto", value={"rest": True, "sick": True})  # fmt: skip
    if v.status == "review_rest":
        return Item(key="today", kind="today", title=v.title, why=v.why, basis=v.basis,
                    action="auto", value={"rest": True, "review": True})  # fmt: skip
    if v.status in ("reviewing", "coach_error"):  # 管家还在看、出错了：如实写，不按规则替它定（§163）
        return Item(key="today", kind="today", title=v.title, why=v.why,
                    value={"original": v.original, v.status: True})  # fmt: skip
    if not v.changed:
        return Item(key="today", kind="today", title=v.title, why=v.why, value={"today": v.today})
    return Item(key="today", kind="today", title=v.title, why=v.why, basis=v.basis, action="auto",
                value={"original": v.original, "today": v.today})  # fmt: skip


def _weather_items(inp: Inputs, today: date) -> list[Item]:
    """极端天气只固定提醒一句（§163 已定：高温中暑风险、重度污染），改不改训练由管家看天气事实定，代码不再自动改。"""
    adv = inp.advice
    if adv is None or adv.level != "avoid":
        return []
    return [Item(key="weather", kind="weather", title="今天的天气不适合在户外练" + (f"：{adv.reasons[0]}" if adv.reasons else ""),
                 why="；".join(adv.reasons), basis="高温预警分级、空气质量 HJ 633", value={"level": adv.level})]  # fmt: skip


def _target_items(inp: Inputs) -> list[Item]:
    from ironm_agent.progression import targets

    out = []
    from ironm_agent.illness import recovering_days

    recovering = recovering_days(inp.illness, date.today())
    steady = [x for x in inp.logs if x.day not in recovering]
    for name, t in targets(inp.plan, steady, inp.decided).items():
        basis = "管家按这次的记录定的" if t.by == "coach" else "管家没定，照上次的重量和次数"
        out.append(Item(key=f"target:{name}", kind="target", title=f"{name} 下次 {t.text()}",
                        why=t.why, basis=basis, action="auto",
                        value={"exercise": name, "weight_kg": t.weight_kg, "reps": t.reps,
                               "sets": t.sets, "move": t.action, "by": t.by}))  # fmt: skip
    return out


def _food_items(inp: Inputs) -> list[Item]:
    """每日热量和蛋白质（事实）。规则的热量调整建议去掉了：热量只在管家复盘里调（§163 需求 6）。"""
    by = {m.key: m for m in inp.snapshot.metrics}
    kcal, protein = by.get("kcal_target"), by.get("protein_target")
    out = []
    if kcal is not None and kcal.value:
        p = (
            f"、蛋白质 {protein.display or round(protein.value)} 克"
            if protein and protein.value
            else ""
        )
        why = (f"按公式计算，加上调整量 {inp.diet.kcal:+d} 千卡（{inp.diet.reason}）"
               if inp.diet else "按基础代谢、活动水平和目标计算")  # fmt: skip
        out.append(Item(key="kcal", kind="kcal", title=f"每天约 {round(kcal.value)} 千卡{p}",
                        why=why, basis=kcal.source, action="auto",
                        value={"kcal": round(kcal.value),
                               "protein": protein.value if protein else None}))  # fmt: skip
    return out


def _goal_items(inp: Inputs) -> list[Item]:
    from ironm_agent.goal import progress

    if inp.goal is None:
        return []
    trend = next((m for m in inp.snapshot.metrics if m.key == "weight_trend"), None)
    p = progress(inp.goal, inp.snapshot.readings.weight, trend, inp.snapshot.today)
    title = f"目标体重 {inp.goal.value:g} 公斤"
    if p["predicted"]:
        d = date.fromisoformat(p["predicted"])
        title += f"，按现在的速度预计 {d.year}年{d.month}月{d.day}日达成"
    out = [Item(key="goal", kind="goal", title=title, why=p["message"] or p["missing"] or p["pace"],
                basis="体重趋势（直线回归）" + ("；减重速度〔K37〕" if p["pace"] else ""),
                value={"status": p["status"], "predicted": p["predicted"]})]  # fmt: skip
    if p["retest"]["due"]:
        out.append(Item(key="retest", kind="retest", title="该复测了", why=p["retest"]["text"],
                        basis="每 4–6 周复测一次（经验）"))  # fmt: skip
    return out


def _proposed(inp: Inputs) -> bool:
    return inp.review is not None and any(
        d.type == "propose" and not d.undone for d in inp.review.done
    )


def _review_items(inp: Inputs) -> list[Item]:
    """管家复盘里已经生效的调整（§85），给页面和管家消息看；撤销了的不再列出。"""
    if inp.review is None:
        return []
    out = [Item(key=d.key, kind="proposal" if d.type == "propose" else "review", title=d.title, why=d.why,
                basis=d.basis,
                action="confirm" if d.type == "propose" else "info" if d.type in ("note", "ask") else "auto",
                value={"type": d.type, "expect": d.expect, **d.value})
           for d in inp.review.done if not d.undone]  # fmt: skip
    # 今天核对完的以前的调整、4 周阶段小结（§89）：只告诉他
    out += [Item(key=f"review:checked:{i}", kind="review", title="上次的调整效果怎么样", why=x,
                 value={"type": "checked"}) for i, x in enumerate(inp.review.checked)]  # fmt: skip
    if inp.review.stage:
        out.append(Item(key="review:stage", kind="review", title="这 4 周的阶段小结",
                        why=inp.review.stage, value={"type": "stage"}))  # fmt: skip
    return out


def compute(inp: Inputs, today: date) -> list[Item]:
    """算出当前方案（顺序：今天、提醒、管家复盘的调整、待确认、饮食、目标、下次目标）。"""
    items = [
        *_review_items(inp),
        _today_item(inp, today),
        *_weather_items(inp, today),
    ]  # 规则的提醒（反复疼、连续没练、中断、平台期）和每周复盘建议去掉了：都交给管家复盘（§163）
    items += _food_items(inp)
    items += _goal_items(inp)
    items += _target_items(inp)
    order = {
        "today": 0,
        "weather": 1,
        "alert": 2,
        "review": 3,
        "proposal": 4,
        "kcal": 5,
        "goal": 6,
        "retest": 7,
        "target": 8,
    }
    return sorted(items, key=lambda x: order[x.kind])


def diff(old: State | None, items: Sequence[Item], today: date, version: int) -> list[Change]:
    """和上一版比：新增、改了、解除。今天那一项换了一天也算改了（每天的调整）。"""
    at = datetime.now(UTC)
    before = {x.key: x for x in old.items} if old else {}
    out = []

    def change(kind: ChangeKind, x: Item, prev: Item | None) -> Change:
        return Change(id=uuid.uuid4().hex[:16], at=at, day=today, version=version, key=x.key,
                      kind=x.kind, change=kind, before=prev.title if prev else "",
                      after=x.title if kind != "removed" else "", why=x.why, basis=x.basis,
                      status=x.action)  # fmt: skip

    for x in items:
        prev = before.pop(x.key, None)
        if x.key == "today" and x.value.get("reviewing"):
            continue  # "管家正在看"不是一次调整：不记、不推给他；看完了再按定下的记（复核 11-05）
        if prev is None:
            out.append(change("added", x, None))
        elif (
            prev.title != x.title
            or prev.action != x.action
            or (x.kind == "today" and old is not None and old.day != today)
        ):
            out.append(change("changed", x, prev))
    out += [change("removed", x, x) for x in before.values()]
    return out


# ---- 存储 -----------------------------------------------------------------------------------


class CoachStore(Protocol):
    async def get(self, user_id: str) -> State | None: ...
    async def save(self, user_id: str, state: State, changes: Sequence[Change]) -> None: ...
    async def history(self, user_id: str, limit: int = 30) -> list[Change]: ...
    async def log(self, user_id: str, changes: Sequence[Change]) -> None: ...
    async def update(self, user_id: str, change: Change) -> None: ...


class CoachBook:
    """内存版（测试用）。"""

    def __init__(self) -> None:
        self.states: dict[str, State] = {}
        self.changes: dict[str, list[Change]] = {}

    async def get(self, user_id: str) -> State | None:
        return self.states.get(user_id)

    async def save(self, user_id: str, state: State, changes: Sequence[Change]) -> None:
        self.states[user_id] = state
        self.changes.setdefault(user_id, []).extend(changes)

    async def history(self, user_id: str, limit: int = 30) -> list[Change]:
        return list(reversed(self.changes.get(user_id, [])))[:limit]

    async def log(self, user_id: str, changes: Sequence[Change]) -> None:
        self.changes.setdefault(user_id, []).extend(changes)

    async def update(self, user_id: str, change: Change) -> None:
        self.changes[user_id] = [
            change if c.id == change.id else c for c in self.changes.get(user_id, [])
        ]


DDL = (
    """
CREATE TABLE IF NOT EXISTS ironm_coach_state (
    user_id    text PRIMARY KEY,
    content    text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
)
""",
    """
CREATE TABLE IF NOT EXISTS ironm_coach_change (
    id         text PRIMARY KEY,
    user_id    text NOT NULL,
    content    text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
)
""",
    "CREATE INDEX IF NOT EXISTS ironm_coach_change_user ON ironm_coach_change (user_id, created_at)",
)


class PgCoach:
    """数据库版：方案和每条调整都用 mirobody 的加密函数加密。"""

    def __init__(self) -> None:
        self._ready = False

    async def _q(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        from mirobody.utils.db import execute_query

        if not self._ready:
            for ddl in DDL:
                await execute_query(ddl, {}, log_sql=False)
            self._ready = True
        rows = await execute_query(sql, params, log_sql=False)
        return rows if isinstance(rows, list) else []

    async def get(self, user_id: str) -> State | None:
        rows = await self._q(
            "SELECT decrypt_content(content) AS content FROM ironm_coach_state WHERE user_id = :uid",
            {"uid": user_id},
        )
        return State.model_validate_json(rows[0]["content"]) if rows else None

    async def save(self, user_id: str, state: State, changes: Sequence[Change]) -> None:
        await self._q(
            "INSERT INTO ironm_coach_state (user_id, content) VALUES (:uid, encrypt_content(:c))"
            " ON CONFLICT (user_id) DO UPDATE SET content = EXCLUDED.content, updated_at = now()",
            {"uid": user_id, "c": state.model_dump_json()},
        )
        await self.log(user_id, changes)

    async def log(self, user_id: str, changes: Sequence[Change]) -> None:
        """只记调整经历，不动当前方案。"""
        for ch in changes:
            await self._q(
                "INSERT INTO ironm_coach_change (id, user_id, content)"
                " VALUES (:id, :uid, encrypt_content(:c))",
                {"id": ch.id, "uid": user_id, "c": ch.model_dump_json()},
            )

    async def history(self, user_id: str, limit: int = 30) -> list[Change]:
        rows = await self._q(
            "SELECT decrypt_content(content) AS content FROM ironm_coach_change"
            " WHERE user_id = :uid ORDER BY created_at DESC LIMIT :n",
            {"uid": user_id, "n": limit},
        )
        return [Change.model_validate_json(r["content"]) for r in rows]

    async def update(self, user_id: str, change: Change) -> None:
        """改一条调整经历（到期核对后写上效果，§89）。"""
        await self._q(
            "UPDATE ironm_coach_change SET content = encrypt_content(:c)"
            " WHERE id = :id AND user_id = :uid",
            {"id": change.id, "uid": user_id, "c": change.model_dump_json()},
        )


_default: CoachStore | None = None


def default_coach() -> CoachStore:
    global _default
    if _default is None:
        _default = PgCoach()
    return _default


# ---- 重新评估 -------------------------------------------------------------------------------


@dataclass
class Deps:
    """重新评估要读的东西（测试时换成内存版）。"""

    snapshot: Callable[[str], Awaitable[Snapshot]]
    training: Any
    pain: Any
    goals: Any
    diet: Any
    store: CoachStore
    weather: Callable[[str], Awaitable[Any]] | None = None
    illness: Any = None  # illness.IllnessStore（§46）
    day: Any = None  # day_state.DayStore（§54）
    memory: Any = None  # memory_store.MemoryStore：认孕期、心脏病这类特殊情况（§95）
    meals: Any = None  # meals.MealStore：按记的吃和体重变化估实际消耗（§118）


async def _gather(user_id: str, deps: Deps, today: date) -> Inputs:
    snap = await deps.snapshot(user_id)
    inp = Inputs(snapshot=snap)

    async def safely(what: str, coro: Awaitable[Any]) -> Any:
        try:
            return await coro
        except Exception as e:  # 某一部分读不到时，其余照常评估
            _log.warning("coach input unavailable: part=%s error_type=%s", what, type(e).__name__)
            return None

    if deps.memory is not None:
        inp.memory = await safely("memory", deps.memory.items(user_id)) or []
    stored = await safely("plan", deps.training.plan(user_id))
    if stored is not None:
        inp.plan, inp.since = stored.plan, stored.since
    rows = await safely(
        "logs", deps.training.workouts(user_id, today - timedelta(days=HISTORY_DAYS))
    )
    inp.logs = [x.log for x in rows or []]
    from ironm_agent.plan_layers import load as load_temps

    inp.temps = await load_temps(deps.training, user_id)
    inp.pains = await safely("pain", deps.pain.since(user_id, today - timedelta(days=14))) or []
    if inp.memory:  # 说好了的那处，之前的疼不再算（§158）
        from ironm_agent.body_now import fresh

        inp.pains = fresh(inp.pains, inp.memory)
    if hasattr(deps.pain, "details"):  # 细节给管家复盘看（§163）；和上面同样去掉好了以前的
        kept = set(inp.pains)
        rows = await safely("pain details", deps.pain.details(user_id, today - timedelta(days=14))) or []
        inp.pain_details = [x for x in rows if (x["part"], x["day"]) in kept]
    inp.goal = await safely("goal", deps.goals.get(user_id))
    inp.diet = await safely("diet", deps.diet.current(user_id))
    if deps.meals is not None:  # 和饮食页同一个算法：管家复盘看到的实际消耗和饮食页一致（§118）
        from ironm_agent.diet_adjust import OBSERVE_DAYS, by_day, observed

        rows = await safely(
            "meals", deps.meals.since(user_id, today - timedelta(days=OBSERVE_DAYS - 1))
        )
        if rows is not None:
            inp.seen = observed(by_day(rows), snap.readings.weight, today)[0]
    if deps.day is not None:
        inp.day = await safely("day", deps.day.get(user_id, today))
    if deps.illness is not None:
        inp.illness = (
            await safely(
                "illness", deps.illness.since(user_id, today - timedelta(days=HISTORY_DAYS))
            )
            or []
        )
    if deps.weather is not None:
        from ironm_agent import weather

        wx = await safely("weather", deps.weather(user_id))
        inp.advice = weather.assess(wx) if wx is not None else None
        inp.forecast = tuple(getattr(wx, "days", ()) or ()) if wx is not None else ()
    return inp


async def evaluate(
    user_id: str, deps: Deps, *, reason: str, today: date | None = None, force: bool = True
) -> tuple[State, list[Change]]:
    """重新评估当前方案。force=False（每天第一次）时，今天已经评估过就直接用上一版。"""
    async with state_lock(user_id):
        return await _evaluate(
            user_id, deps, reason=reason, today=today or date.today(), force=force
        )


_STATE_LOCKS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]] = (
    weakref.WeakKeyDictionary()
)


def loop_lock(
    table: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]], key: str
) -> asyncio.Lock:
    """按事件循环分开的每人一把锁（锁只能在建它的循环里等）。"""
    return table.setdefault(asyncio.get_running_loop(), {}).setdefault(key, asyncio.Lock())


def state_lock(user_id: str) -> asyncio.Lock:
    """每人一把：读出管家的方案、改、再存回去的都要拿着它，免得并发的两次互相覆盖（§132 审查）。
    只在单进程里有效，多进程要换数据库锁。"""
    return loop_lock(_STATE_LOCKS, user_id)


async def _evaluate(
    user_id: str, deps: Deps, *, reason: str, today: date, force: bool
) -> tuple[State, list[Change]]:
    old = await deps.store.get(user_id)
    if not force and old is not None and old.day == today:
        return old, []
    inp = await _gather(user_id, deps, today)
    review = (
        old.review
        if old is not None and old.review is not None and old.review.day == today
        else None
    )
    inp.review = review
    inp.decided = old.decided() if old is not None else {}
    items = compute(inp, today)
    version = (old.version + 1) if old else 1
    changes = diff(old, items, today, version)
    if old is not None and old.day == today and not changes:
        if (
            items != old.items
        ):  # 只是说明变了（比如管家定的下次目标和规则一样，§132）：照存、不加版本、不记经历
            fresh = old.model_copy(update={"items": items})
            await deps.store.save(user_id, fresh, [])
            return fresh, []
        return old, []
    state = State(version=version, day=today, at=datetime.now(UTC), reason=reason, items=items,
                  seen=old.seen if old else 0, choices=old.choices if old else {},
                  report_seen=old.report_seen if old else None,
                  review=review, stage_day=old.stage_day if old else None,
                  stage_text=old.stage_text if old else "", week_day=old.week_day if old else None,
                  targets=old.targets if old else {})  # fmt: skip
    await deps.store.save(user_id, state, changes)
    _log.info("coach evaluated %s", json.dumps({"version": version, "items": len(items),
                                                "changes": len(changes)}))  # fmt: skip
    return state, changes


_BACKGROUND: set[asyncio.Task[Any]] = set()


def evaluate_later(user_id: str, deps: Deps, reason: str) -> None:
    """有新情况时在后台重新评估；出错只记错误类型，不影响这次请求。"""

    async def go() -> None:
        try:
            await evaluate(user_id, deps, reason=reason)
        except Exception as e:
            _log.warning("coach evaluate failed: error_type=%s", type(e).__name__)

    task = asyncio.create_task(go())
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)


def record_plan_later(
    store: CoachStore, user_id: str, draft: dict[str, Any], *, undone: bool = False
) -> None:
    """在后台记一条改计划的调整经历；出错只记错误类型。"""

    async def go() -> None:
        try:
            await record_plan(store, user_id, draft, undone=undone)
        except Exception as e:
            _log.warning("plan change log failed: error_type=%s", type(e).__name__)

    task = asyncio.create_task(go())
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)


async def settle() -> None:
    """等后台评估做完（测试用）。"""
    while _BACKGROUND:
        await asyncio.gather(*list(_BACKGROUND), return_exceptions=True)


# ---- 对话里的管家消息（spec [2026-10-23] §26）---------------------------------------------------


def pending(state: State, today: date) -> list[Item]:
    """还要用户确认的：确认过的同一条不再问；暂不的今天不再问；调整内容变了就重新问。"""
    out = []
    for x in state.items:
        if x.action != "confirm":
            continue
        c = state.choices.get(x.key)
        if c is not None and c.title == x.title and (c.decision == "accept" or c.day == today):
            continue
        out.append(x)
    return out


def unseen(state: State, history: Sequence[Change]) -> list[Change]:
    """用户在对话里还没看过的自动生效和提醒类改动（新的在后）。"""
    return [c for c in reversed(history)
            if c.version > state.seen and c.status != "confirm" and c.change in ("added", "changed", "removed")]  # fmt: skip


async def mark_seen(store: CoachStore, user_id: str, version: int) -> None:
    async with state_lock(user_id):
        state = await store.get(user_id)
        if state is not None and version > state.seen:
            await store.save(
                user_id, state.model_copy(update={"seen": min(version, state.version)}), []
            )


def _temp_after(draft: dict[str, Any]) -> str:
    t = draft.get("temp") or {}
    if not t:
        return ""
    return f"临时调整 {t.get('start')}–{t.get('end')}：" + "；".join(str(x) for x in t.get("lines") or [])


async def record_plan(
    store: CoachStore, user_id: str, draft: dict[str, Any], *, undone: bool = False
) -> bool:
    """确认或撤销一份按操作改的计划、临时调整时，记一条调整经历：哪几条操作、原因（spec [2026-10-23] §45、§163）。"""
    ops = draft.get("ops") or (draft.get("temp") or {}).get("ops")
    if not ops:
        return False
    state = await store.get(user_id)
    whys = "；".join(dict.fromkeys(str(o.get("why") or "") for o in ops if o.get("why")))
    record = Change(id=uuid.uuid4().hex[:16], at=datetime.now(UTC), day=date.today(),
                    version=state.version if state else 0, key="plan", kind="proposal",
                    change="removed" if undone else "accepted", before="",
                    after=str(draft.get("changes") or _temp_after(draft))[:200], why=whys[:120],
                    basis=f"{len(ops)} 条操作", status="confirm")  # fmt: skip
    await store.log(user_id, [record])
    return True


async def decide(
    store: CoachStore,
    user_id: str,
    key: str,
    decision: Literal["accept", "later"],
    today: date | None = None,
) -> Item | None:
    """记下用户对一条待确认调整的选择，并写进调整经历；没有这条时返回 None。"""
    async with state_lock(user_id):
        return await _decide(store, user_id, key, decision, today or date.today())


async def mark_report_seen(store: CoachStore, user_id: str, monday: date) -> bool:
    """对话页的周报消息点掉了（§147）：记下是哪一周的，这周不再出；还没有方案时返回 False。"""
    async with state_lock(user_id):
        state = await store.get(user_id)
        if state is None:
            return False
        await store.save(user_id, state.model_copy(update={"report_seen": monday}), [])
        return True


async def _decide(
    store: CoachStore, user_id: str, key: str, decision: Literal["accept", "later"], today: date
) -> Item | None:
    state = await store.get(user_id)
    item = state.item(key) if state is not None else None
    if state is None or item is None:
        return None
    if item.action != "confirm":
        return None
    choices = {**state.choices, key: Choice(decision=decision, title=item.title, day=today)}
    record = Change(id=uuid.uuid4().hex[:16], at=datetime.now(UTC), day=today, version=state.version,
                    key=key, kind=item.kind, change="accepted" if decision == "accept" else "declined",
                    after=item.title, why=item.why, basis=item.basis, status="confirm")  # fmt: skip
    await store.save(user_id, state.model_copy(update={"choices": choices}), [record])
    _log.info("coach decision %s", json.dumps({"decision": decision, "kind": item.kind}))
    return item
