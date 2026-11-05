"""进行中的训练（spec [2026-10-23] §71）：选动作开始训练，一组一组记重量、次数、用时，结束后存成训练记录。

存在服务端（浏览器只存登录凭证，§19）：每改一处都存，刷新、锁屏回来接着练。一个人同时只有一个；
6 小时没动自动结束，只保存完成的组。另存每个动作改过的组间休息秒数，下次照用。
数据库版内容用 mirobody 的加密函数加密；日志不写内容。
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from ironm_agent.exercises import library
from ironm_agent.progression import history, next_target
from ironm_agent.training import LogItem, Plan, SetDone, WorkoutLog

IDLE = timedelta(hours=6)
REST_BARBELL, REST_DEFAULT = 120, 90
MAX_MINUTES = 300
DEFAULT_SETS = 3


class LiveSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weight_kg: float | None = Field(default=None, ge=0, le=500)
    reps: int | None = Field(default=None, ge=0, le=100)
    seconds: int | None = Field(default=None, ge=1, le=3600)  # 这组用时：计时了才有
    done: bool = False
    at: datetime | None = None  # 完成的时间


class LiveItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercise: str = Field(min_length=1, max_length=30)
    timed: bool = False  # 计时类：记秒数不记次数
    rest: int = Field(default=REST_DEFAULT, ge=15, le=600)  # 组间休息秒数
    target: str = Field(default="", max_length=40)  # 计划目标或上次做的，给他看
    best: float | None = Field(
        default=None, ge=0, le=1000
    )  # 以前最好的一组的估算最大重量（§92 破纪录）
    plan_kg: float | None = Field(
        default=None, ge=0, le=1000
    )  # 开始时预填的重量（计划目标或上次的），训练中自己调的上下限按它算（§104）
    sets: list[LiveSet] = Field(default_factory=list, max_length=20)
    cardio: bool = False  # 有氧：一段一行只记时长（页面填分钟，存秒）（§130）


class Live(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    started: datetime
    updated: datetime
    session: str = Field(default="", max_length=16)  # 按计划的哪一次（从首页开始时）
    items: list[LiveItem] = Field(default_factory=list, max_length=15)
    no_heavier: bool = False  # 不能比计划重：特殊人群（§95）或这次训练说过疼（§104）


class LiveError(ValueError):
    """用户可以看懂的错误（接口返回 422）。"""


class LiveStore(Protocol):
    async def get(self, user_id: str) -> Live | None: ...
    async def save(self, user_id: str, live: Live) -> None: ...
    async def clear(self, user_id: str) -> None: ...
    async def rests(self, user_id: str) -> dict[str, int]: ...
    async def set_rest(self, user_id: str, exercise: str, seconds: int) -> None: ...


class LiveBook:
    """内存版（测试用）。"""

    def __init__(self) -> None:
        self.live: dict[str, Live] = {}
        self.rest: dict[str, dict[str, int]] = {}

    async def get(self, user_id: str) -> Live | None:
        return self.live.get(user_id)

    async def save(self, user_id: str, live: Live) -> None:
        self.live[user_id] = live

    async def clear(self, user_id: str) -> None:
        self.live.pop(user_id, None)

    async def rests(self, user_id: str) -> dict[str, int]:
        return dict(self.rest.get(user_id, {}))

    async def set_rest(self, user_id: str, exercise: str, seconds: int) -> None:
        self.rest.setdefault(user_id, {})[exercise] = seconds


DDL = """
CREATE TABLE IF NOT EXISTS ironm_live (
    user_id    text PRIMARY KEY,
    content    text,
    rests      text,
    updated_at timestamptz NOT NULL DEFAULT now()
)
"""


class PgLive:
    """数据库版：每人一行；进行中的训练和改过的休息秒数都加密后存。"""

    def __init__(self) -> None:
        self._ready = False

    async def _q(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        from mirobody.utils.db import execute_query

        if not self._ready:
            await execute_query(DDL, {}, log_sql=False)
            self._ready = True
        rows = await execute_query(sql, params, log_sql=False)
        return rows if isinstance(rows, list) else []

    async def _row(self, user_id: str) -> dict[str, Any]:
        rows = await self._q(
            "SELECT decrypt_content(content) AS content, decrypt_content(rests) AS rests"
            " FROM ironm_live WHERE user_id = :uid",
            {"uid": user_id},
        )
        return rows[0] if rows else {}

    async def get(self, user_id: str) -> Live | None:
        raw = (await self._row(user_id)).get("content")
        return Live.model_validate_json(raw) if raw else None

    async def save(self, user_id: str, live: Live) -> None:
        await self._q(
            "INSERT INTO ironm_live (user_id, content) VALUES (:uid, encrypt_content(:c))"
            " ON CONFLICT (user_id) DO UPDATE SET content = EXCLUDED.content, updated_at = now()",
            {"uid": user_id, "c": live.model_dump_json()},
        )

    async def clear(self, user_id: str) -> None:
        await self._q(
            "UPDATE ironm_live SET content = NULL, updated_at = now() WHERE user_id = :uid",
            {"uid": user_id},
        )

    async def rests(self, user_id: str) -> dict[str, int]:
        raw = (await self._row(user_id)).get("rests")
        return {str(k): int(v) for k, v in json.loads(raw).items()} if raw else {}

    async def set_rest(self, user_id: str, exercise: str, seconds: int) -> None:
        rests = await self.rests(user_id)
        rests[exercise] = seconds
        await self._q(
            "INSERT INTO ironm_live (user_id, rests) VALUES (:uid, encrypt_content(:r))"
            " ON CONFLICT (user_id) DO UPDATE SET rests = EXCLUDED.rests",
            {"uid": user_id, "r": json.dumps(rests, ensure_ascii=False)},
        )


_default: LiveStore | None = None


def default_live() -> LiveStore:
    global _default
    if _default is None:
        _default = PgLive()
    return _default


# ---- 开始、预先填好 ---------------------------------------------------------------------------


def _move(name: str) -> Any:
    return next((x for x in library().exercises if x.name == name), None)


def rest_of(name: str, rests: dict[str, int]) -> int:
    """组间休息：改过的照用；杠铃动作 120 秒，其余 90 秒。"""
    if name in rests:
        return rests[name]
    move = _move(name)
    return REST_BARBELL if move is not None and "杠铃" in move.equipment else REST_DEFAULT


def new_item(
    name: str, plan: Plan | None, logs: Sequence[WorkoutLog], rests: dict[str, int]
) -> LiveItem:
    """一个动作：重量和次数按计划目标、上次做的预先填好；都没有时空着。"""
    move = _move(name)
    cardio = bool(move is not None and move.part == "有氧")
    timed = bool(move is not None and move.timed) or cardio
    planned = (
        next((x for s in sorted(plan.sessions, key=lambda s: s.day != date.today().isoweekday())
              for x in s.items if x.exercise == name), None)  # 今天那一次排前面（复核 11-05）
        if plan
        else None
    )
    last = history(name, logs)
    n = planned.sets if planned else len(last[0][1]) if last else DEFAULT_SETS
    weight: float | None = None
    reps: int | None = None
    seconds: int | None = None
    target = ""
    if planned is not None and (t := next_target(planned, logs)) is not None:
        weight, target = t.weight_kg, f"目标 {t.text()}"
        nums = [int(x) for x in t.reps.replace("–", "-").split("-") if x.strip().isdigit()]
        reps = nums[0] if nums else None
    elif last:
        prev = last[0][1][-1]
        weight, reps, seconds = prev.weight_kg, prev.reps or None, prev.seconds
        target = "上次 " + "、".join(
            (f"{x.seconds} 秒" if not x.reps and x.seconds else
             f"{x.weight_kg:g}×{x.reps}" if x.weight_kg else f"{x.reps} 次") for x in last[0][1]
        )  # fmt: skip
    elif planned is not None:
        target = f"计划 {planned.sets} 组 × {planned.reps}"
    if cardio:  # 有氧（§130）：一段，按计划写的分钟或上次的时长预填，不记重量和次数
        mins = (
            re.match(r"\s*(\d+)", planned.reps)
            if planned is not None and "分钟" in planned.reps
            else None
        )
        secs = int(mins.group(1)) * 60 if mins else (last[0][1][-1].seconds if last else None)
        target = (
            f"计划 {planned.reps}"
            if planned is not None
            else (f"上次 {round(secs / 60)} 分钟" if secs else "")
        )
        return LiveItem(exercise=name, timed=True, cardio=True, rest=rest_of(name, rests), target=target[:40],
                        best=None, plan_kg=None, sets=[LiveSet(seconds=secs)])  # fmt: skip
    one = LiveSet(
        weight_kg=weight, reps=None if timed else reps, seconds=seconds if timed else None
    )
    sets = [one.model_copy() for _ in range(max(1, min(n, 20)))]
    if planned is None and last:  # 没有计划目标：逐组照上次填
        sets = [LiveSet(weight_kg=x.weight_kg, reps=None if timed else (x.reps or None),
                        seconds=x.seconds if timed else None) for x in last[0][1][:20]]  # fmt: skip
    return LiveItem(exercise=name, timed=timed, rest=rest_of(name, rests), target=target[:40],
                    best=best_e1rm(name, logs), plan_kg=sets[0].weight_kg, sets=sets)  # fmt: skip


def _e1rm(weight: float | None, reps: int | None) -> float | None:
    from ironm_agent.protools.strength import epley

    if not weight or not reps or reps > 30:
        return None
    return round(epley(weight, reps), 1)


def best_e1rm(name: str, logs: Sequence[WorkoutLog]) -> float | None:
    """这个动作以前最好的一组（估算最大重量）；没做过、没记重量返回 None。"""
    got = [e for _, sets in history(name, logs) for s in sets if (e := _e1rm(s.weight_kg, s.reps))]
    return max(got) if got else None


def records(log: WorkoutLog, before: Sequence[WorkoutLog]) -> list[dict[str, Any]]:
    """这次破了的纪录：最好的一组超过以前最好的（以前没做过的不算）。"""
    out = []
    for item in log.items:
        old = best_e1rm(item.exercise, before)
        sets = [(s, e) for s in item.done_sets if (e := _e1rm(s.weight_kg, s.reps))]
        if old is None or not sets:
            continue
        s, e = max(sets, key=lambda x: x[1])
        if e > old:
            out.append({"exercise": item.exercise, "weight_kg": s.weight_kg, "reps": s.reps,
                        "e1rm": e, "before": old})  # fmt: skip
    return out


def known(name: str) -> str:
    move = _move(" ".join(str(name).split()))
    if move is None:
        raise LiveError("动作库里没有这个动作")
    return str(move.name)


def stale(live: Live, now: datetime) -> bool:
    return now - live.updated > IDLE


# ---- 结束：存成训练记录 -------------------------------------------------------------------------


def summary(live: Live, now: datetime) -> dict[str, Any]:
    done = [(it, s) for it in live.items for s in it.sets if s.done]
    return {
        "minutes": minutes_of(live, now),
        "exercises": len({it.exercise for it, _ in done}),
        "sets": len(done),
        "volume": round(
            sum((s.weight_kg or 0) * (s.reps or 0) for it, s in done if not it.timed), 1
        ),
    }


def minutes_of(live: Live, now: datetime) -> int:
    return max(1, min(MAX_MINUTES, round((now - live.started).total_seconds() / 60)))


def to_log(
    live: Live, day: date, now: datetime, rpe: int | None = None, note: str = ""
) -> WorkoutLog | None:
    """只含完成的组；一组都没完成时为 None。"""
    items = [
        LogItem(
            exercise=it.exercise,
            done_sets=[
                SetDone(reps=s.reps or 0, weight_kg=s.weight_kg, seconds=s.seconds, at=s.at)
                for s in it.sets
                if s.done
            ],
        )
        for it in live.items
        if any(s.done for s in it.sets)
    ]
    if not items:
        return None
    return WorkoutLog(day=day, session=live.session, items=items[:15], rpe=rpe,
                      minutes=minutes_of(live, now), note=note)  # fmt: skip


def fresh(session: str, items: list[LiveItem], now: datetime) -> Live:
    return Live(id=uuid.uuid4().hex[:16], started=now, updated=now, session=session, items=items)
