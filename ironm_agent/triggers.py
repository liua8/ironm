"""触发型调整（spec [2026-10-23] §18 需求 5）：不等每周复盘，满足条件就在首页提醒并给出一键处理。

- 同一部位 14 天内有 2 天以上说疼：建议换掉加重这个部位负担的动作，并就医评估（同一天说几次算一次）；
- 计划里连续 3 次以上没练（上次练过之后计划里的训练日）：建议更轻的安排；
- 中断 7 天以上后回来：今天的版本按中断时长降量（7–14 天约七成，更久约一半，经验）；
- 主要动作的估算最大重量（Epley）3 周以上没有提高：提示平台期，建议换刺激方式。
都是规则，不调用模型。说疼的记录只存部位和日期，部位加密存储；日志不写内容。
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal, Protocol

from ironm_agent.body import joint_code
from ironm_agent.casefile import PARTS, _hurts
from ironm_agent.ddl import run_ddl
from ironm_agent.protools.movement import JOINT_NAMES, find
from ironm_agent.protools.strength import epley
from ironm_agent.training import Plan, WorkoutLog

type Kind = Literal["pain", "missed", "gap", "plateau"]
type Action = Literal["proposal", "today", "info"]

PAIN_DAYS = 14
PAIN_TIMES = 2
MISSED = 3
GAP = 7
GAP_LONG = 14
GAP_SCALE = 0.7
GAP_LONG_SCALE = 0.5
PLATEAU_DAYS = 21
PLATEAU_LOOKBACK = 63


@dataclass(frozen=True)
class Trigger:
    kind: Kind
    title: str
    detail: str  # 给用户看的一句话：发现了什么、建议怎么做
    action: Action  # proposal：生成调整方案；today：今天的版本已经按这个改了；info：只提醒
    tip: str = ""  # 交给训练教练改计划时的说明（action 为 proposal 时）
    part: str = ""  # 反复疼的部位（pain）
    exercises: tuple[str, ...] = ()  # 进入平台期的动作（plateau）


def pain_parts(text: str) -> list[str]:
    """这句话里本人说正疼的部位（与共享档案同一套判断）。"""
    return [k for k, p in PARTS.items() if _hurts(p, text)]


def pain_triggers(
    events: Sequence[tuple[str, date]], plan: Plan | None, today: date
) -> list[Trigger]:
    days: dict[str, set[date]] = defaultdict(set)
    for part, day in events:
        if 0 <= (today - day).days < PAIN_DAYS:
            days[part].add(day)
    out = []
    for part, seen in days.items():
        if len(seen) < PAIN_TIMES:
            continue
        name = JOINT_NAMES.get(part, part)
        loaded = _loading(plan, part)
        swap = (
            f"计划里的{'、'.join(loaded)}会加重{name}负担，建议先换掉"
            if loaded
            else "练的时候避开引起疼的动作"
        )
        out.append(
            Trigger(
                "pain",
                f"{name}最近反复疼",
                f"最近 {PAIN_DAYS} 天有 {len(seen)} 天说{name}疼：{swap}，并找医生或康复师评估。",
                "proposal" if loaded else "info",
                f"最近 {PAIN_DAYS} 天有 {len(seen)} 天说{name}疼：把{'、'.join(loaded)}换成对{name}友好的动作。"
                if loaded
                else "",
                part=part,
            )
        )
    return out


def _loading(plan: Plan | None, part: str) -> list[str]:
    names = []
    for s in plan.sessions if plan else ():
        for it in s.items:
            m = find(it.exercise)
            if m is not None and part in m.tag.stress:
                names.append(it.exercise)
    return list(dict.fromkeys(names))


def _last_done(logs: Sequence[WorkoutLog], today: date) -> date | None:
    days = [x.day for x in logs if x.done and x.day < today]
    return max(days) if days else None


def missed_trigger(
    plan: Plan | None,
    logs: Sequence[WorkoutLog],
    since: date | None,
    today: date,
    sick: Collection[date] = (),
) -> Trigger | None:
    """上次练过之后（或计划开始之后），计划里的训练日一次都没练、到了 3 次以上；生病的日子不算（§46）。"""
    if plan is None:
        return None
    if any(x.done and x.day == today for x in logs):
        return None
    last = _last_done(logs, today)
    start = max(d for d in (last, since, today - timedelta(days=28)) if d is not None)
    planned = {s.day for s in plan.sessions}
    n = sum(
        1
        for k in range(1, (today - start).days)
        if (start + timedelta(days=k)).isoweekday() in planned
        and start + timedelta(days=k) not in sick
    )
    if n < MISSED:
        return None
    return Trigger(
        "missed",
        "计划连着几次没练",
        f"计划里已经连着 {n} 次没练了：可以换个更轻、更好坚持的安排（比如少一天、每次短一点）。",
        "proposal",
        f"计划里已经连着 {n} 次没练：换成更轻、更容易坚持的安排（少一天或每次更短）。",
    )


def gap_scale(logs: Sequence[WorkoutLog], today: date) -> tuple[float, str] | None:
    """中断 7 天以上后回来：今天按原量的几成练、为什么。"""
    if any(x.done and x.day == today for x in logs):
        return None
    last = _last_done(logs, today)
    if last is None:
        return None
    gap = (today - last).days
    if gap < GAP:
        return None
    scale = GAP_SCALE if gap <= GAP_LONG else GAP_LONG_SCALE
    return scale, f"上次训练是 {gap} 天前，先按原量的约 {round(scale * 10)} 成恢复"


def gap_trigger(logs: Sequence[WorkoutLog], today: date) -> Trigger | None:
    g = gap_scale(logs, today)
    if g is None:
        return None
    return Trigger("gap", "中断后回来", f"{g[1]}：今天的版本已经按这个减了组数。", "today")


def best_e1rm(logs: Sequence[WorkoutLog], exercise: str, start: date, end: date) -> float | None:
    """这段时间里这个动作的最好估算最大重量（只算 1–12 次的组，次数太多估得不准）。"""
    best = None
    for log in logs:
        if not (start <= log.day <= end) or not log.done:
            continue
        for it in log.items:
            m, n = find(it.exercise), find(exercise)
            if it.exercise != exercise and (
                m is None or n is None or m.exercise.id != n.exercise.id
            ):
                continue
            for s in it.performed():
                if s.weight_kg and 1 <= s.reps <= 12:
                    e = epley(s.weight_kg, s.reps)
                    best = e if best is None else max(best, e)
    return best


def plateau_triggers(
    plan: Plan | None, logs: Sequence[WorkoutLog], today: date, sick: Collection[date] = ()
) -> list[Trigger]:
    """主要动作：最近 3 周的最好成绩没超过之前（再往前 6 周内）的最好成绩，而且最近 3 周至少练了 2 次。
    最近 3 周里有生病的日子时不判断（§46）。"""
    out: list[Trigger] = []
    recent_start = today - timedelta(days=PLATEAU_DAYS - 1)
    if any(recent_start <= d <= today for d in sick):
        return out
    earlier_start = today - timedelta(days=PLATEAU_LOOKBACK - 1)
    stuck = []
    for s in plan.sessions if plan else ():
        for it in s.items:
            m = find(it.exercise)
            if m is None or not m.compound or it.exercise in stuck:
                continue
            times = sum(
                1
                for x in logs
                if x.done and recent_start <= x.day <= today
                and any(i.exercise == it.exercise and i.performed() for i in x.items)
            )  # fmt: skip
            before = best_e1rm(logs, it.exercise, earlier_start, recent_start - timedelta(days=1))
            now_ = best_e1rm(logs, it.exercise, recent_start, today)
            if times >= 2 and before is not None and now_ is not None and now_ <= before:
                stuck.append(it.exercise)
    if stuck:
        names = "、".join(stuck)
        out.append(
            Trigger(
                "plateau",
                "进入平台期",
                f"{names}的估算最大重量 3 周以上没有提高：可以换个刺激方式（换次数区间、换变式或安排一周减量）。",
                "proposal",
                f"{names}的估算最大重量 3 周以上没有提高（平台期）：换刺激方式，比如换次数区间或换相近的变式。",
                exercises=tuple(stuck),
            )
        )
    return out


def detect(
    plan: Plan | None,
    logs: Sequence[WorkoutLog],
    since: date | None,
    pains: Sequence[tuple[str, date]],
    today: date,
    sick: Collection[date] = (),
) -> list[Trigger]:
    out = pain_triggers(pains, plan, today)
    for t in (missed_trigger(plan, logs, since, today, sick), gap_trigger(logs, today)):
        if t is not None:
            out.append(t)
    return out + plateau_triggers(plan, logs, today, sick)


# ---- 说疼的记录 -------------------------------------------------------------------------------


class PainStore(Protocol):
    async def add(self, user_id: str, part: str, day: date, **detail: str) -> None: ...
    async def since(self, user_id: str, start: date) -> list[tuple[str, date]]: ...
    async def details(self, user_id: str, start: date) -> list[dict[str, Any]]: ...


PAIN_DETAIL = ("side", "exercise", "level")  # 管家记疼时一起交的：左右、在做哪个动作、轻重（§163）


class PainBook:
    """内存版（测试用）。"""

    def __init__(self) -> None:
        self.rows: dict[str, list[tuple[str, date]]] = {}
        self.more: dict[str, list[dict[str, str]]] = {}  # 和 rows 一一对应的细节

    async def add(self, user_id: str, part: str, day: date, **detail: str) -> None:
        self.rows.setdefault(user_id, []).append((part, day))
        self.more.setdefault(user_id, []).append({k: str(detail.get(k) or "") for k in PAIN_DETAIL})

    async def since(self, user_id: str, start: date) -> list[tuple[str, date]]:
        return _coded([x for x in self.rows.get(user_id, []) if x[1] >= start])

    async def details(self, user_id: str, start: date) -> list[dict[str, Any]]:
        rows, more = self.rows.get(user_id, []), self.more.get(user_id, [])
        out = []
        for i, (part, day) in enumerate(rows):
            code = joint_code(part)
            if code is not None and day >= start:
                out.append({"part": code, "day": day, **(more[i] if i < len(more) else {})})
        return out


def _coded(rows: list[tuple[str, date]]) -> list[tuple[str, date]]:
    """§57 之前存的 knee、back 这类读的时候换成关节编码，认不出的不要。"""
    out = []
    for part, day in rows:
        code = joint_code(part)
        if code is not None:
            out.append((code, day))
    return out


DDL = """
CREATE TABLE IF NOT EXISTS ironm_pain_events (
    id         text PRIMARY KEY,
    user_id    text NOT NULL,
    content    text NOT NULL,
    day        date NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
)
"""


class PgPain:
    """数据库版：部位用 mirobody 的加密函数加密。"""

    def __init__(self) -> None:
        self._ready = False

    async def _q(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        from mirobody.utils.db import execute_query

        if not self._ready:
            await run_ddl(DDL)
            self._ready = True
        rows = await execute_query(sql, params, log_sql=False)
        return rows if isinstance(rows, list) else []

    async def add(self, user_id: str, part: str, day: date, **detail: str) -> None:
        extra = {k: str(detail.get(k) or "") for k in PAIN_DETAIL if detail.get(k)}
        content = json.dumps({"part": part, **extra}, ensure_ascii=False) if extra else part  # 细节和部位一起加密
        await self._q(
            "INSERT INTO ironm_pain_events (id, user_id, content, day)"
            " VALUES (:id, :uid, encrypt_content(:part), :day)",
            {"id": uuid.uuid4().hex, "uid": user_id, "part": content, "day": day},
        )

    async def _rows(self, user_id: str, start: date) -> list[dict[str, Any]]:
        rows = await self._q(
            "SELECT decrypt_content(content) AS part, day FROM ironm_pain_events"
            " WHERE user_id = :uid AND day >= :start ORDER BY day",
            {"uid": user_id, "start": start},
        )
        return [{**_unpack(str(r["part"])), "day": r["day"]} for r in rows]

    async def since(self, user_id: str, start: date) -> list[tuple[str, date]]:
        return _coded([(x["part"], x["day"]) for x in await self._rows(user_id, start)])

    async def details(self, user_id: str, start: date) -> list[dict[str, Any]]:
        out = []
        for x in await self._rows(user_id, start):
            code = joint_code(x["part"])
            if code is not None:
                out.append({**x, "part": code})
        return out


def _unpack(content: str) -> dict[str, Any]:
    """存的是部位，或部位和细节的 JSON（§163 之后）。"""
    if content.startswith("{"):
        try:
            got = json.loads(content)
            if isinstance(got, dict) and got.get("part"):
                return {"part": str(got["part"]), **{k: str(got.get(k) or "") for k in PAIN_DETAIL}}
        except ValueError:
            pass
    return {"part": content, **dict.fromkeys(PAIN_DETAIL, "")}


_default: PainStore | None = None


def default_pain() -> PainStore:
    global _default
    if _default is None:
        _default = PgPain()
    return _default
