"""训练计划与训练记录（spec [2026-10-23] §9）：写入前先给预览，用户确认才写入，写入后能撤销。

- 计划：每人一份当前的每周计划；改计划时新版本成为当前计划，旧版本留着（撤销时恢复）；
- 记录：每次训练一条（日期、按计划的哪一次、动作组次重量、感受 1–10、备注）；
- 预览（草稿）：Agent 生成或修改计划、整理训练记录时先存成草稿，24 小时内确认有效，确认一次只写入一次；
- 内容加密存储（与 mirobody 对话内容同一种加密），日志里不写内容；
- 测试和考题用内存版（TrainingBook），线上用数据库版（PgTraining），两者接口一样。
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from ironm_agent.memory_extract import digits
from ironm_agent.numbers import written_numbers

_log = logging.getLogger("ironm_agent.training")

DRAFT_HOURS = 24
MERGE_MINUTES = 30  # 这么久之内没确认的计划预览，再改一下时在它上面接着改（§45）
WEEKDAYS = "一二三四五六日"
type Kind = Literal["plan", "log"]
type DraftState = Literal["pending", "confirmed", "cancelled", "undone"]


def now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid.uuid4().hex[:16]


def weekday_name(day: int) -> str:
    return f"周{WEEKDAYS[day - 1]}"


# ---- 计划与记录的内容 ------------------------------------------------------------------------


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class PlanItem(_Model):
    exercise: str = Field(min_length=1, max_length=30)
    sets: int = Field(ge=1, le=10)
    reps: str = Field(min_length=1, max_length=20)  # "8–12"、"每侧 8 次"、"30–45 秒"
    load: str = Field(default="", max_length=40)  # 重量或强度说明
    note: str = Field(default="", max_length=80)

    @field_validator("reps", mode="before")
    @classmethod
    def _reps(cls, v: Any) -> Any:
        return str(v) if isinstance(v, int | float) else v

    def line(self) -> str:
        extra = "，".join(x for x in (self.load, self.note) if x)
        return f"{self.exercise} {self.sets}×{self.reps}" + (f"（{extra}）" if extra else "")


class Session(_Model):
    day: int = Field(ge=1, le=7)  # 1 = 周一 … 7 = 周日
    name: str = Field(min_length=1, max_length=16)
    minutes: int = Field(default=45, ge=10, le=180)
    items: list[PlanItem] = Field(min_length=1, max_length=10)

    def line(self) -> str:
        return f"{weekday_name(self.day)} {self.name}（约 {self.minutes} 分钟）：" + "、".join(
            x.line() for x in self.items
        )


class Plan(_Model):
    title: str = Field(min_length=1, max_length=24)
    goal: str = Field(default="", max_length=16)
    days_per_week: int = Field(ge=1, le=7)
    sessions: list[Session] = Field(min_length=1, max_length=7)

    @model_validator(mode="after")
    def _days(self) -> Plan:
        days = [s.day for s in self.sessions]
        if len(days) != len(set(days)):
            raise ValueError("同一天排了两次训练")
        self.sessions.sort(key=lambda s: s.day)
        self.days_per_week = len(self.sessions)
        return self

    def session_on(self, day: date) -> Session | None:
        return next((s for s in self.sessions if s.day == day.isoweekday()), None)

    def lines(self) -> list[str]:
        head = f"《{self.title}》每周 {self.days_per_week} 练" + (
            f"，目标{self.goal}" if self.goal else ""
        )
        return [head, *(s.line() for s in self.sessions)]


class SetDone(_Model):
    """一组实际做了多少（spec [2026-10-23] §18 需求 4）。"""

    reps: int = Field(ge=0, le=100)
    weight_kg: float | None = Field(default=None, ge=0, le=500)


_EACH = re.compile(r"\d+")


class LogItem(_Model):
    exercise: str = Field(min_length=1, max_length=30)
    sets: int | None = Field(default=None, ge=1, le=20)
    reps: str = Field(default="", max_length=20)
    weight_kg: float | None = Field(default=None, ge=0, le=500)
    done_sets: list[SetDone] = Field(
        default_factory=list, max_length=20
    )  # 每组的重量和次数（可不填）

    @field_validator("reps", mode="before")
    @classmethod
    def _reps(cls, v: Any) -> Any:
        return str(v) if isinstance(v, int | float) else (v or "")

    @model_validator(mode="after")
    def _count(self) -> LogItem:
        if self.done_sets and self.sets is None:  # 只填了每组的：组数按填了几组算
            self.sets = len(self.done_sets)
        return self

    def performed(self) -> list[SetDone]:
        """每组做了多少：填了每组的用每组的；否则按"3 组 × 8 次"或"3 组，8、8、7 次"展开；看不出来时为空。"""
        if self.done_sets:
            return list(self.done_sets)
        if not self.sets or not self.reps or re.search(r"秒|分钟|米|公里|[-–~～到至]", self.reps):
            return []
        each = [int(x) for x in _EACH.findall(self.reps)]
        if len(each) == 1:
            each = each * self.sets
        if len(each) != self.sets:
            return []
        return [SetDone(reps=r, weight_kg=self.weight_kg) for r in each]

    def line(self) -> str:
        if self.done_sets:
            sets = "、".join(
                (f"{x.weight_kg:g}×{x.reps}" if x.weight_kg is not None else f"{x.reps} 次")
                for x in self.done_sets
            )
            return f"{self.exercise} {sets}"
        parts = [self.exercise]
        if self.sets:
            parts.append(f"{self.sets} 组" + (f" × {self.reps} 次" if self.reps else ""))
        elif self.reps:
            parts.append(f"{self.reps} 次")
        if self.weight_kg is not None:
            parts.append(f"{self.weight_kg:g} 公斤")
        return " ".join(parts)


class WorkoutLog(_Model):
    day: date
    session: str = Field(default="", max_length=16)  # 按计划的哪一次（如"下肢"），没有计划时为空
    items: list[LogItem] = Field(default_factory=list, max_length=15)
    done: bool = True
    rpe: int | None = Field(default=None, ge=1, le=10)  # 感受（1 很轻松 … 10 到极限）
    minutes: int | None = Field(default=None, ge=1, le=300)
    note: str = Field(default="", max_length=80)

    def line(self) -> str:
        head = f"{self.day.month}月{self.day.day}日（{weekday_name(self.day.isoweekday())}）"
        what = self.session or "训练"
        parts = [f"{head} {what}{'' if self.done else '（没练完）'}"]
        if self.items:
            parts.append("、".join(x.line() for x in self.items))
        if self.minutes:
            parts.append(f"{self.minutes} 分钟")
        if self.rpe:
            parts.append(f"感受 {self.rpe} 分")
        if self.note:
            parts.append(self.note)
        return "：".join(parts[:2]) + ("，" + "，".join(parts[2:]) if len(parts) > 2 else "")


_LIMITS = {"title": 24, "goal": 16, "name": 16, "exercise": 30, "reps": 20, "load": 40, "note": 80}


def _clip(raw: Any) -> Any:
    """模型写的计划常常某个字段长一点、动作多一两个：截短，而不是整份作废。"""
    if isinstance(raw, dict):
        out = {}
        for k, v in raw.items():
            if isinstance(v, str) and k in _LIMITS:
                v = v.strip()[: _LIMITS[k]]
            elif k == "items" and isinstance(v, list):
                v = v[:10]
            elif k == "sessions" and isinstance(v, list):
                v = v[:7]
            out[k] = _clip(v)
        return out
    if isinstance(raw, list):
        return [_clip(x) for x in raw]
    return raw


def parse_plan(raw: Any) -> tuple[Plan | None, str]:
    try:
        return Plan.model_validate(_clip(raw)), ""
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(x) for x in first.get("loc", ()))
        return None, f"计划的格式不对（{where}：{first.get('msg', '')}）"


def parse_log(raw: Any, today: date) -> tuple[WorkoutLog | None, str]:
    if isinstance(raw, dict) and not raw.get("day"):
        raw = {**raw, "day": today.isoformat()}
    try:
        log = WorkoutLog.model_validate(_clip(raw))
    except ValidationError as e:
        first = e.errors()[0]
        return None, f"训练记录的格式不对（{'.'.join(str(x) for x in first.get('loc', ()))}）"
    if log.day > today or (today - log.day).days > 14:
        return None, "训练记录的日期只能是今天或最近两周"
    return log, ""


def trusted_log(log: WorkoutLog, said: str, plan: Plan | None) -> WorkoutLog:
    """训练记录里的数字只能来自用户这句话（或当前计划里那一次的安排），对不上的去掉，不编造。"""
    allowed = set(written_numbers(said)) | {
        float(x) for x in digits(said, chinese=True) if x.replace(".", "", 1).isdigit()
    }
    session = next((s for s in plan.sessions if s.name == log.session), None) if plan else None
    planned = set(written_numbers(" ".join(x.line() for x in session.items))) if session else set()

    def ok(v: float | None, pool: set[float]) -> bool:
        return v is None or v in pool

    items = []
    for x in log.items:
        pool = allowed | planned
        reps_ok = all(v in pool for v in written_numbers(x.reps))
        done = [d for d in x.done_sets if d.reps in allowed and ok(d.weight_kg, allowed)]
        items.append(
            x.model_copy(
                update={
                    "sets": x.sets if ok(x.sets, pool) else None,
                    "reps": x.reps if reps_ok else "",
                    "weight_kg": x.weight_kg if ok(x.weight_kg, allowed) else None,
                    "done_sets": done if len(done) == len(x.done_sets) else [],
                }
            )
        )
    return log.model_copy(
        update={
            "items": items,
            "rpe": log.rpe if ok(log.rpe, allowed) else None,
            "minutes": log.minutes if ok(log.minutes, allowed | planned) else None,
        }
    )


# ---- 这一轮要不要写计划或记录（规则）-----------------------------------------------------------

PLAN_TASK = re.compile(
    r"(?:计划|课表).{0,4}(?:改|换|调|减|加|删|重新|更新)"
    r"|(?:排|做|制定|定|设计|生成|给我|来|出|重新|更新|调整|修改|改一?下)[^，。？！?!]{0,14}(?:计划|课表)"
    r"|把?周[一二三四五六日天].{0,8}(?:改|换|调|挪|移|取消|不练|休息|删|去掉)"
    r"|(?:这周|本周|下周).{0,12}(?:出差|练不了|没时间|减成|改成|调整|少练|多练|加一练|只能练|轻一?点|轻很多|减量)"
    r"|(?:计划|每次训练|训练量).{0,6}(?:轻一?点|轻很多|减量|减半)"
)
LOG_TASK = re.compile(
    r"(?:记录|记一下|记下|打卡)[^？?]{0,12}(?:训练|练|跑|运动|组|次)"
    r"|(?:今天|今早|今晚|刚才|刚刚|昨天|昨晚|早上|晚上|上午|下午|中午)[^，。？?！!]{0,12}"
    r"(?:练了|练完|做了|完成了|跑了)[^？?]{0,40}(?:组|次|公斤|千克|kg|分钟|公里|计划|分)"
    r"|(?:感觉|感受|自评)\s*(?:打)?\s*\d+\s*分"
)
# 问句不是在报训练（"今天练完能吃夜宵吗"）；饮食计划不是训练计划
_QUESTION = re.compile(
    r"[？?]\s*$|[吗呢]\s*$|怎么|为什么|是不是|要不要|能不能|该不该|可以吗|行不行|会不会"
)
_DIET = re.compile(r"饮食|食谱|吃|菜单|营养|餐")
_TRAINING_WORD = re.compile(r"训练|练|健身|运动")


def task_of(text: str) -> Kind | None:
    """这句话是要记一次训练（log）、排或改训练计划（plan），还是都不是。"""
    if LOG_TASK.search(text) and not _QUESTION.search(text):
        return "log"
    if PLAN_TASK.search(text) and not (_DIET.search(text) and not _TRAINING_WORD.search(text)):
        return "plan"
    return None


# ---- 存储 -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class StoredPlan:
    id: str
    plan: Plan
    created: datetime

    @property
    def since(self) -> date:
        """这份计划从哪天开始用（本地日期）。"""
        return self.created.astimezone().date()


@dataclass(frozen=True)
class StoredLog:
    id: str
    log: WorkoutLog
    created: datetime


@dataclass(frozen=True)
class Draft:
    id: str
    kind: Kind
    content: dict[str, Any]  # {"plan": …, "changes": "…"} 或 {"log": …}
    state: DraftState
    created: datetime
    applied: str | None = None  # 确认后写入的计划或记录
    previous: str | None = None  # 确认时被替换的旧计划（撤销时恢复）

    def expired(self, at: datetime | None = None) -> bool:
        return (at or now()) - self.created > timedelta(hours=DRAFT_HOURS)

    def json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "state": self.state,
            "expired": self.state == "pending" and self.expired(),
            "created": self.created.isoformat(),
            "expires": (self.created + timedelta(hours=DRAFT_HOURS)).isoformat(),
            **self.content,
        }


class TrainingStore(Protocol):
    async def plan(self, user_id: str) -> StoredPlan | None: ...
    async def workouts(self, user_id: str, since: date) -> list[StoredLog]: ...
    async def add_draft(self, user_id: str, kind: Kind, content: dict[str, Any]) -> Draft: ...
    async def draft(self, user_id: str, draft_id: str) -> Draft | None: ...
    async def pending_plan(self, user_id: str, minutes: int = MERGE_MINUTES) -> Draft | None: ...
    async def confirm(self, user_id: str, draft_id: str) -> Draft | None: ...
    async def cancel(self, user_id: str, draft_id: str) -> Draft | None: ...
    async def undo(self, user_id: str, draft_id: str) -> Draft | None: ...
    async def log(self, user_id: str, log: WorkoutLog) -> StoredLog: ...
    async def delete_workout(self, user_id: str, workout_id: str) -> bool: ...


def _plan_of(content: dict[str, Any]) -> Plan:
    return Plan.model_validate(content["plan"])


def _log_of(content: dict[str, Any]) -> WorkoutLog:
    return WorkoutLog.model_validate(content["log"])


class TrainingBook:
    """内存版：测试与考题用。"""

    def __init__(self) -> None:
        self._plans: dict[str, list[tuple[StoredPlan, bool]]] = {}  # (计划, 是否当前)
        self._logs: dict[str, list[StoredLog]] = {}
        self._drafts: dict[str, dict[str, Draft]] = {}

    def seed(self, user_id: str, plan: Plan | None, logs: Sequence[WorkoutLog] = ()) -> None:
        if plan is not None:
            self._plans[user_id] = [(StoredPlan(new_id(), plan, now()), True)]
        self._logs[user_id] = [StoredLog(new_id(), x, now()) for x in logs]

    async def plan(self, user_id: str) -> StoredPlan | None:
        return next((p for p, active in self._plans.get(user_id, []) if active), None)

    async def workouts(self, user_id: str, since: date) -> list[StoredLog]:
        rows = [x for x in self._logs.get(user_id, []) if x.log.day >= since]
        return sorted(rows, key=lambda x: (x.log.day, x.created))

    async def add_draft(self, user_id: str, kind: Kind, content: dict[str, Any]) -> Draft:
        d = Draft(new_id(), kind, content, "pending", now())
        self._drafts.setdefault(user_id, {})[d.id] = d
        return d

    async def draft(self, user_id: str, draft_id: str) -> Draft | None:
        return self._drafts.get(user_id, {}).get(draft_id)

    async def pending_plan(self, user_id: str, minutes: int = MERGE_MINUTES) -> Draft | None:
        since = now() - timedelta(minutes=minutes)
        rows = [d for d in self._drafts.get(user_id, {}).values()
                if d.kind == "plan" and d.state == "pending" and d.created >= since]  # fmt: skip
        return max(rows, key=lambda d: d.created, default=None)

    def _put(self, user_id: str, d: Draft) -> Draft:
        self._drafts[user_id][d.id] = d
        return d

    async def confirm(self, user_id: str, draft_id: str) -> Draft | None:
        d = await self.draft(user_id, draft_id)
        if d is None or d.state != "pending" or d.expired():
            return None
        if d.kind == "plan":
            plans = self._plans.setdefault(user_id, [])
            previous = next((p.id for p, active in plans if active), None)
            self._plans[user_id] = [(p, False) for p, _ in plans]
            new = StoredPlan(new_id(), _plan_of(d.content), now())
            self._plans[user_id].append((new, True))
            return self._put(
                user_id, replace(d, state="confirmed", applied=new.id, previous=previous)
            )
        row = StoredLog(new_id(), _log_of(d.content), now())
        self._logs.setdefault(user_id, []).append(row)
        return self._put(user_id, replace(d, state="confirmed", applied=row.id))

    async def cancel(self, user_id: str, draft_id: str) -> Draft | None:
        d = await self.draft(user_id, draft_id)
        if d is None or d.state != "pending":
            return None
        return self._put(user_id, replace(d, state="cancelled"))

    async def undo(self, user_id: str, draft_id: str) -> Draft | None:
        d = await self.draft(user_id, draft_id)
        if d is None or d.state != "confirmed":
            return None
        if d.kind == "plan":
            plans = self._plans.get(user_id, [])
            if not any(p.id == d.applied and active for p, active in plans):
                return None  # 之后又换过计划：不能再撤销这一次
            self._plans[user_id] = [(p, p.id == d.previous) for p, _ in plans if p.id != d.applied]
        else:
            self._logs[user_id] = [x for x in self._logs.get(user_id, []) if x.id != d.applied]
        return self._put(user_id, replace(d, state="undone"))

    async def log(self, user_id: str, log: WorkoutLog) -> StoredLog:
        row = StoredLog(new_id(), log, now())
        self._logs.setdefault(user_id, []).append(row)
        return row

    async def delete_workout(self, user_id: str, workout_id: str) -> bool:
        rows = self._logs.get(user_id, [])
        kept = [x for x in rows if x.id != workout_id]
        self._logs[user_id] = kept
        return len(kept) != len(rows)


DDL = (
    """
CREATE TABLE IF NOT EXISTS ironm_plan (
    id         text PRIMARY KEY,
    user_id    text NOT NULL,
    content    text NOT NULL,
    active     boolean NOT NULL,
    previous   text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
)
""",
    "CREATE INDEX IF NOT EXISTS ironm_plan_user ON ironm_plan (user_id, active)",
    # 曾经加过"每人只有一个当前计划"的唯一索引，会和确认、撤销里先写入后换下的顺序冲突：删掉，改用按人加锁
    "DROP INDEX IF EXISTS ironm_plan_one_active",
    """
CREATE TABLE IF NOT EXISTS ironm_workout (
    id         text PRIMARY KEY,
    user_id    text NOT NULL,
    day        date NOT NULL,
    content    text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
)
""",
    "CREATE INDEX IF NOT EXISTS ironm_workout_user ON ironm_workout (user_id, day)",
    """
CREATE TABLE IF NOT EXISTS ironm_draft (
    id         text PRIMARY KEY,
    user_id    text NOT NULL,
    kind       text NOT NULL,
    content    text NOT NULL,
    state      text NOT NULL,
    applied    text,
    previous   text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
)
""",
)
_FRESH = f"created_at > now() - interval '{DRAFT_HOURS} hours'"
# 同一个人的确认、撤销一个接一个地做（事务结束时自动放开）
_LOCK = "SELECT pg_advisory_xact_lock(hashtext('ironm_training:' || :uid))"
_DRAFT = (
    "SELECT id, kind, decrypt_content(content) AS content, state, applied, previous, created_at"
    " FROM ironm_draft WHERE user_id = :uid AND id = :id"
)


def _draft_row(r: dict[str, Any]) -> Draft:
    return Draft(
        id=str(r["id"]),
        kind=cast(Kind, r["kind"]),
        content=json.loads(r.get("content") or "{}"),
        state=cast(DraftState, r["state"]),
        created=r["created_at"],
        applied=r.get("applied"),
        previous=r.get("previous"),
    )


class PgTraining:
    """数据库版：与 mirobody 同一个数据库里 iron-m 自己的表；内容用 mirobody 的加密函数加密。

    确认与撤销各用一条语句完成（几张表的改动要么都做、要么都不做）；同一份预览点两次确认只写入一次。
    """

    def __init__(self) -> None:
        self._ready = False

    async def _ready_tables(self) -> None:
        from mirobody.utils.db import execute_query

        if not self._ready:
            for ddl in DDL:
                await execute_query(ddl, {}, log_sql=False)
            self._ready = True

    async def _q(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        from mirobody.utils.db import execute_query

        await self._ready_tables()
        rows = await execute_query(sql, params or {}, log_sql=False)
        return rows if isinstance(rows, list) else []

    async def plan(self, user_id: str) -> StoredPlan | None:
        rows = await self._q(
            "SELECT id, decrypt_content(content) AS content, created_at FROM ironm_plan"
            " WHERE user_id = :uid AND active ORDER BY created_at DESC LIMIT 1",
            {"uid": user_id},
        )
        if not rows:
            return None
        r = rows[0]
        return StoredPlan(str(r["id"]), _plan_of(json.loads(r["content"])), r["created_at"])

    async def workouts(self, user_id: str, since: date) -> list[StoredLog]:
        rows = await self._q(
            "SELECT id, decrypt_content(content) AS content, created_at FROM ironm_workout"
            " WHERE user_id = :uid AND day >= :since ORDER BY day, created_at",
            {"uid": user_id, "since": since},
        )
        return [
            StoredLog(str(r["id"]), _log_of(json.loads(r["content"])), r["created_at"])
            for r in rows
        ]

    async def add_draft(self, user_id: str, kind: Kind, content: dict[str, Any]) -> Draft:
        d = Draft(new_id(), kind, content, "pending", now())
        await self._q(
            "INSERT INTO ironm_draft (id, user_id, kind, content, state, created_at)"
            " VALUES (:id, :uid, :kind, encrypt_content(:content), 'pending', :created)",
            {"id": d.id, "uid": user_id, "kind": kind, "content": _dumps(content), "created": d.created},
        )  # fmt: skip
        return d

    async def draft(self, user_id: str, draft_id: str) -> Draft | None:
        rows = await self._q(_DRAFT, {"uid": user_id, "id": draft_id})
        return _draft_row(rows[0]) if rows else None

    async def pending_plan(self, user_id: str, minutes: int = MERGE_MINUTES) -> Draft | None:
        rows = await self._q(
            "SELECT id, kind, decrypt_content(content) AS content, state, applied, previous, created_at"
            " FROM ironm_draft WHERE user_id = :uid AND kind = 'plan' AND state = 'pending'"
            f" AND created_at > now() - interval '{int(minutes)} minutes'"
            " ORDER BY created_at DESC LIMIT 1",
            {"uid": user_id},
        )
        return _draft_row(rows[0]) if rows else None

    async def confirm(self, user_id: str, draft_id: str) -> Draft | None:
        """确认一份预览：在一个事务里先按人加锁，再改预览状态、换下旧计划、写入新计划（或记录）。

        锁让同一个人的两份预览同时确认时一个接一个地做：后一个能看到前一个刚写入的计划，并把它换下，
        不会留下两个当前计划；同一份预览点两次，第二次看到它已经确认过，什么也不写。
        """
        from mirobody.utils.db import transaction

        await self._ready_tables()
        d = await self.draft(user_id, draft_id)
        if d is None or d.state != "pending" or d.expired():
            return None
        target = new_id()
        async with transaction() as tx:
            await tx.execute(_LOCK, {"uid": user_id})
            if d.kind == "plan":
                rows = await tx.execute(
                    "UPDATE ironm_draft SET state = 'confirmed', applied = :target, updated_at = now(),"
                    " previous = (SELECT id FROM ironm_plan WHERE user_id = :uid AND active"
                    " ORDER BY created_at DESC LIMIT 1)"
                    f" WHERE id = :id AND user_id = :uid AND kind = 'plan' AND state = 'pending' AND {_FRESH}"
                    " RETURNING content, previous",
                    {"id": draft_id, "uid": user_id, "target": target},
                )
                if not rows:
                    return None
                await tx.execute(
                    "UPDATE ironm_plan SET active = false, updated_at = now() WHERE user_id = :uid AND active",
                    {"uid": user_id},
                )
                await tx.execute(
                    "INSERT INTO ironm_plan (id, user_id, content, active, previous)"
                    " VALUES (:target, :uid, :content, true, :previous)",
                    {"target": target, "uid": user_id, "content": rows[0]["content"],
                     "previous": rows[0]["previous"]},
                )  # fmt: skip
            else:
                rows = await tx.execute(
                    "UPDATE ironm_draft SET state = 'confirmed', applied = :target, updated_at = now()"
                    f" WHERE id = :id AND user_id = :uid AND kind = 'log' AND state = 'pending' AND {_FRESH}"
                    " RETURNING content",
                    {"id": draft_id, "uid": user_id, "target": target},
                )
                if not rows:
                    return None
                await tx.execute(
                    "INSERT INTO ironm_workout (id, user_id, day, content) VALUES (:target, :uid, :day, :content)",
                    {"target": target, "uid": user_id, "day": _log_of(d.content).day,
                     "content": rows[0]["content"]},
                )  # fmt: skip
        return await self.draft(user_id, draft_id)

    async def cancel(self, user_id: str, draft_id: str) -> Draft | None:
        rows = await self._q(
            "UPDATE ironm_draft SET state = 'cancelled', updated_at = now()"
            " WHERE id = :id AND user_id = :uid AND state = 'pending' RETURNING id",
            {"id": draft_id, "uid": user_id},
        )
        return await self.draft(user_id, draft_id) if rows else None

    async def undo(self, user_id: str, draft_id: str) -> Draft | None:
        """撤销一次确认：计划回到上一版（之后又换过计划时不能撤销），记录删掉。同样在一个加锁的事务里。"""
        from mirobody.utils.db import transaction

        await self._ready_tables()
        async with transaction() as tx:
            await tx.execute(_LOCK, {"uid": user_id})
            rows = await tx.execute(
                "UPDATE ironm_draft SET state = 'undone', updated_at = now()"
                " WHERE id = :id AND user_id = :uid AND state = 'confirmed' AND (kind = 'log' OR EXISTS ("
                " SELECT 1 FROM ironm_plan p WHERE p.id = ironm_draft.applied AND p.user_id = :uid AND p.active))"
                " RETURNING kind, applied, previous",
                {"id": draft_id, "uid": user_id},
            )
            if not rows:
                return None
            kind, applied, previous = rows[0]["kind"], rows[0]["applied"], rows[0]["previous"]
            if kind == "plan":
                await tx.execute(
                    "DELETE FROM ironm_plan WHERE id = :applied AND user_id = :uid",
                    {"applied": applied, "uid": user_id},
                )
                if previous:
                    await tx.execute(
                        "UPDATE ironm_plan SET active = true, updated_at = now()"
                        " WHERE id = :previous AND user_id = :uid",
                        {"previous": previous, "uid": user_id},
                    )
            else:
                await tx.execute(
                    "DELETE FROM ironm_workout WHERE id = :applied AND user_id = :uid",
                    {"applied": applied, "uid": user_id},
                )
        return await self.draft(user_id, draft_id)

    async def log(self, user_id: str, log: WorkoutLog) -> StoredLog:
        row = StoredLog(new_id(), log, now())
        await self._q(
            "INSERT INTO ironm_workout (id, user_id, day, content, created_at)"
            " VALUES (:id, :uid, :day, encrypt_content(:content), :created)",
            {"id": row.id, "uid": user_id, "day": log.day, "content": _dumps({"log": _dump(log)}),
             "created": row.created},
        )  # fmt: skip
        return row

    async def delete_workout(self, user_id: str, workout_id: str) -> bool:
        rows = await self._q(
            "DELETE FROM ironm_workout WHERE id = :id AND user_id = :uid RETURNING id",
            {"id": workout_id, "uid": user_id},
        )
        return bool(rows)


def _dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")


def _dumps(content: dict[str, Any]) -> str:
    return json.dumps(content, ensure_ascii=False)


def plan_content(plan: Plan, changes: str = "", **extra: Any) -> dict[str, Any]:
    """extra：按操作改的计划还带上操作、没改成的原因等（§45）。"""
    return {"plan": _dump(plan), "changes": changes, **extra}


def log_content(log: WorkoutLog) -> dict[str, Any]:
    return {"log": _dump(log)}


_default: PgTraining | None = None


def default_training() -> TrainingStore:
    global _default
    if _default is None:
        _default = PgTraining()
    return _default


# ---- 档案里的计划与记录、本周进度 ----------------------------------------------------------------


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


@dataclass(frozen=True)
class Week:
    planned: int  # 本周计划练几次
    due: int  # 截至今天应该练了几次
    done: int  # 本周已经练了几次（完成的记录，同一天算一次）
    sessions: tuple[tuple[Session, bool], ...] = ()  # 本周每一次计划和是否已练

    def line(self) -> str:
        return f"本周已完成 {self.done} 次（计划 {self.planned} 次，截至今天应练 {self.due} 次）"


def week_of(
    plan: Plan | None, logs: Sequence[WorkoutLog], today: date, since: date | None = None
) -> Week:
    """本周进度。since：这份计划从哪天开始用（计划是这周中间才定的，之前那几天不算没练）。

    每条完成的记录只对上一次计划：先按日期对（那天该练的那一次），对不上再按名字对到还没对上的、
    日期不晚于记录那天的那一次（周一、周三、周五都叫"全身"时，记一次不会三天都打勾）。
    """
    start = week_start(today)
    this_week = sorted((x for x in logs if x.done and start <= x.day <= today), key=lambda x: x.day)
    done_days = {x.day for x in this_week}
    if plan is None:
        return Week(0, 0, len(done_days))
    day_of = {s.day: start + timedelta(days=s.day - 1) for s in plan.sessions}
    counted = [s for s in plan.sessions if since is None or day_of[s.day] >= since]
    matched: set[int] = set()
    for log in this_week:
        same_day = [s for s in counted if day_of[s.day] == log.day and s.day not in matched]
        by_name = [s for s in counted if s.name == log.session and s.day not in matched
                   and day_of[s.day] <= log.day]  # fmt: skip
        pick = same_day or by_name
        if pick:
            matched.add(pick[0].day)
    sessions = tuple((s, s.day in matched) for s in counted)
    due = sum(1 for s in counted if s.day <= today.isoweekday())
    return Week(len(counted), due, len(done_days), sessions)


def case_lines(
    plan: Plan | None, logs: Sequence[WorkoutLog], today: date, since: date | None = None
) -> list[str]:
    """共享档案里的计划与最近 7 天的训练记录（规则，不调用模型）。"""
    out: list[str] = []
    if plan is None:
        out.append("当前计划：还没有（可以让训练教练排一份）")
    else:
        out.append("当前计划：" + "；".join(plan.lines()))
        s = plan.session_on(today)
        name = weekday_name(today.isoweekday())
        out.append(f"今天（{name}）按计划：{s.name}" if s else f"今天（{name}）按计划：休息")
    recent = [x for x in logs if (today - x.day).days < 7]
    if recent:
        out.append("最近 7 天的训练记录：" + "；".join(x.line() for x in recent))
    if plan is not None:
        out.append(week_of(plan, logs, today, since).line())
    return out
