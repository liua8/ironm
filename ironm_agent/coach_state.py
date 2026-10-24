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
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from ironm_agent.casefile import Snapshot, readiness
from ironm_agent.metrics import KcalAdjust
from ironm_agent.training import Plan, WorkoutLog, weekday_name

_log = logging.getLogger("ironm_agent.coach_state")

type Kind = Literal["today", "target", "kcal", "goal", "retest", "alert", "proposal"]
type Action = Literal["auto", "confirm", "info"]  # 自动生效 / 要用户确认 / 只提醒
type ChangeKind = Literal["added", "changed", "removed"]

HISTORY_DAYS = 63  # 读多久的训练记录（平台期要看 9 周）


class Item(BaseModel):
    key: str  # 同一项在各版本里的编号，如 today、target:杠铃深蹲、proposal:diet
    kind: Kind
    title: str  # 给人看的一句话
    why: str = ""  # 原因
    basis: str = ""  # 依据（依据库编号、规则或经验）
    action: Action = "info"
    value: dict[str, Any] = Field(default_factory=dict)  # 页面要用的结构化内容


class State(BaseModel):
    version: int
    day: date
    at: datetime
    reason: str  # 这次因为什么重新评估
    items: list[Item]

    def item(self, key: str) -> Item | None:
        return next((x for x in self.items if x.key == key), None)


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
    outcome: str = ""  # 调整后的效果（第 2 步补上）


# ---- 输入与规则 -------------------------------------------------------------------------------


@dataclass
class Inputs:
    snapshot: Snapshot
    plan: Plan | None = None
    since: date | None = None  # 计划从哪天开始用
    logs: list[WorkoutLog] = field(default_factory=list)
    pains: list[tuple[str, date]] = field(default_factory=list)
    goal: Any = None  # goal.Goal
    diet: KcalAdjust | None = None
    advice: Any = None  # weather.Advice


def _today_item(inp: Inputs, today: date) -> Item:
    from ironm_agent.today import build
    from ironm_agent.triggers import gap_scale

    name = weekday_name(today.isoweekday())
    if inp.plan is None:
        return Item(
            key="today", kind="today", title="还没有训练计划", why="可以让训练教练按你的目标排一份"
        )
    session = inp.plan.session_on(today)
    if session is None:
        return Item(key="today", kind="today", title=f"今天（{name}）按计划休息",
                    why="恢复也是训练的一部分", value={"rest": True})  # fmt: skip
    state = readiness(inp.snapshot.readings, "", today)
    gap = gap_scale(inp.logs, today)
    adv = inp.advice
    version = build(
        session,
        tired=state.level == "poor",
        tired_why="；".join(state.reasons),
        indoor=adv is not None and adv.level in ("indoor", "avoid"),
        indoor_why=adv.reasons[0] if adv is not None and adv.reasons else "",
        scale=gap[0] if gap else None,
        scale_why=gap[1] if gap else "",
    )
    if not version.changed:
        return Item(key="today", kind="today", title=f"今天练{session.name}，按原计划",
                    why=f"今天的状态{state.name}，天气不影响训练",
                    value={"today": session.model_dump(mode="json")})  # fmt: skip
    basis = []
    if state.level == "poor":
        basis.append("睡眠〔K07〕、和自己的基线比〔K18〕")
    if adv is not None and adv.level in ("indoor", "avoid"):
        basis.append("空气质量 HJ 633、高温预警分级")
    if gap:
        basis.append("中断后降量（经验）")
    return Item(
        key="today",
        kind="today",
        title=f"今天练{session.name}：" + "；".join(version.changes),
        why="；".join(version.reasons),
        basis="；".join(basis),
        action="auto",
        value={"original": session.model_dump(mode="json"),
               "today": version.session.model_dump(mode="json")},
    )  # fmt: skip


def _target_items(inp: Inputs) -> list[Item]:
    from ironm_agent.progression import targets

    out = []
    for name, t in targets(inp.plan, inp.logs).items():
        basis = {"up": "加重 2–10%〔K03〕", "down": "减重约 10%（经验）"}.get(t.action, "进阶规则")
        out.append(Item(key=f"target:{name}", kind="target", title=f"{name} 下次 {t.text()}",
                        why=t.why, basis=basis, action="auto",
                        value={"exercise": name, "weight_kg": t.weight_kg, "reps": t.reps,
                               "sets": t.sets, "move": t.action}))  # fmt: skip
    return out


def _food_items(inp: Inputs) -> list[Item]:
    from ironm_agent.diet_adjust import propose

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
    proposal, _ = propose(inp.snapshot.metrics, inp.snapshot.profile, inp.diet, inp.snapshot.today)
    if proposal is not None:
        more = "多" if proposal.delta > 0 else "少"
        out.append(Item(key="proposal:diet", kind="proposal", action="confirm",
                        title=f"建议每天{more}吃约 {abs(proposal.delta)} 千卡（{proposal.before} → {proposal.after}）",
                        why=proposal.reason, basis=f"减重速度〔K37〕；{proposal.basis}",
                        value={"delta": proposal.delta, "after": proposal.after}))  # fmt: skip
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


ALERT_BASIS = {
    "pain": "带痛训练的界限〔K33〕、就医信号〔K15〕",
    "missed": "计划完成度规则",
    "gap": "中断后降量（经验）",
    "plateau": "估算最大重量（Epley）；减量周〔K31〕",
}


def _alert_items(inp: Inputs, today: date) -> list[Item]:
    from ironm_agent.triggers import detect

    return [
        Item(key=f"alert:{t.kind}", kind="alert", title=t.title, why=t.detail,
             basis=ALERT_BASIS.get(t.kind, ""),
             action="confirm" if t.action == "proposal" else "info", value={"trigger": t.kind})
        for t in detect(inp.plan, inp.logs, inp.since, inp.pains, today)
    ]  # fmt: skip


def _review_item(inp: Inputs) -> list[Item]:
    from ironm_agent.brief import weekly_review

    if inp.plan is None:
        return []
    tips = weekly_review(inp.snapshot, inp.plan, inp.logs, inp.since)["tips"]
    plan_tips = [t for t in tips if "千卡" not in t]  # 热量的建议由饮食复盘那一项管
    if not plan_tips:
        return []
    return [Item(key="proposal:review", kind="proposal", action="confirm",
                 title="可以按这周的复盘调整训练计划", why="".join(plan_tips)[:200],
                 basis="每周复盘规则（睡眠〔K07〕、心率变异性〔K18〕、完成度）")]  # fmt: skip


def compute(inp: Inputs, today: date) -> list[Item]:
    """按规则算出当前方案（顺序：今天、提醒、待确认、饮食、目标、下次目标）。"""
    items = [_today_item(inp, today), *_alert_items(inp, today), *_review_item(inp)]
    items += _food_items(inp)
    items += _goal_items(inp)
    items += _target_items(inp)
    order = {"today": 0, "alert": 1, "proposal": 2, "kcal": 3, "goal": 4, "retest": 5, "target": 6}
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


async def _gather(user_id: str, deps: Deps, today: date) -> Inputs:
    snap = await deps.snapshot(user_id)
    inp = Inputs(snapshot=snap)

    async def safely(what: str, coro: Awaitable[Any]) -> Any:
        try:
            return await coro
        except Exception as e:  # 某一部分读不到时，其余照常评估
            _log.warning("coach input unavailable: part=%s error_type=%s", what, type(e).__name__)
            return None

    stored = await safely("plan", deps.training.plan(user_id))
    if stored is not None:
        inp.plan, inp.since = stored.plan, stored.since
    rows = await safely(
        "logs", deps.training.workouts(user_id, today - timedelta(days=HISTORY_DAYS))
    )
    inp.logs = [x.log for x in rows or []]
    inp.pains = await safely("pain", deps.pain.since(user_id, today - timedelta(days=14))) or []
    inp.goal = await safely("goal", deps.goals.get(user_id))
    inp.diet = await safely("diet", deps.diet.current(user_id))
    if deps.weather is not None:
        from ironm_agent import weather

        wx = await safely("weather", deps.weather(user_id))
        inp.advice = weather.assess(wx) if wx is not None else None
    return inp


async def evaluate(
    user_id: str, deps: Deps, *, reason: str, today: date | None = None, force: bool = True
) -> tuple[State, list[Change]]:
    """重新评估当前方案。force=False（每天第一次）时，今天已经评估过就直接用上一版。"""
    today = today or date.today()
    old = await deps.store.get(user_id)
    if not force and old is not None and old.day == today:
        return old, []
    inp = await _gather(user_id, deps, today)
    items = compute(inp, today)
    version = (old.version + 1) if old else 1
    changes = diff(old, items, today, version)
    if old is not None and old.day == today and not changes:
        return old, []
    state = State(version=version, day=today, at=datetime.now(UTC), reason=reason, items=items)
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


async def settle() -> None:
    """等后台评估做完（测试用）。"""
    while _BACKGROUND:
        await asyncio.gather(*list(_BACKGROUND), return_exceptions=True)
