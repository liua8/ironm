"""训练记录得出的偏好（spec [2026-10-23] §17）：按规则从训练记录算出，存进记忆，来源标为"训练记录"。

不调用模型、不推测原因。门槛：最近 28 天至少 6 次训练、跨 2 周以上；一条偏好要有至少 3 次记录支持、
占同类记录的 70% 以上。新规律和已有的不一样时，最近 14 天也是新规律才替换；还被数据支持的会刷新时间，
56 天没再被支持的在读取时不再使用（memory_view.DATA_DAYS）。用户自己说过可练时间时，以用户说的为准。
"""

from __future__ import annotations

import logging
import re
import statistics
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from ironm_agent.memory_store import Category, Change, Item, MemoryStore, new_id, now
from ironm_agent.training import Plan, TrainingStore, WorkoutLog, weekday_name

_log = logging.getLogger("ironm_agent.memory_prefs")

WINDOW = 28
RECENT = 14  # 替换已有偏好前，最近 14 天也要是新的规律
MIN_SESSIONS = 6
MIN_SPAN = 14
RECENT_MIN_SESSIONS = 3
RECENT_MIN_SPAN = 7
MIN_SUPPORT = 3
SHARE = 0.7
MAX_DAYS = 3  # "常在周几练"最多列几天
SKIP_SHARE = 0.5
SCHEDULE_ASPECTS = frozenset({"days", "minutes", "frequency"})
EVIDENCE_HEAD = "训练记录（{aspect}）："
_ASPECT = re.compile(r"^训练记录（(\w+)）：")


@dataclass(frozen=True)
class Pref:
    aspect: str  # days / minutes / frequency / intensity / skips
    category: Category
    content: str
    evidence: str


def _done(logs: Sequence[WorkoutLog], today: date, days: int) -> list[WorkoutLog]:
    start = today - timedelta(days=days - 1)
    return sorted((x for x in logs if x.done and start <= x.day <= today), key=lambda x: x.day)


def derive(
    logs: Sequence[WorkoutLog],
    today: date,
    *,
    days: int = WINDOW,
    plan: Plan | None = None,
    min_sessions: int = MIN_SESSIONS,
    min_span: int = MIN_SPAN,
) -> dict[str, Pref]:
    done = _done(logs, today, days)
    if len(done) < min_sessions or (today - done[0].day).days + 1 < min_span:
        return {}
    n = len(done)
    period = f"{(today - timedelta(days=days - 1)).isoformat()} 到 {today.isoformat()}"
    out: dict[str, Pref] = {}

    def add(aspect: str, category: Category, content: str, fact: str) -> None:
        out[aspect] = Pref(
            aspect, category, content, EVIDENCE_HEAD.format(aspect=aspect) + f"{period}，{fact}"
        )

    # 常在周几练：取次数最多的几天，合起来占到七成、每天至少 2 次
    weekdays = Counter(x.day.isoweekday() for x in done)
    picked: list[int] = []
    for d, c in weekdays.most_common():
        if c < 2 or len(picked) >= MAX_DAYS:
            break
        picked.append(d)
        covered = sum(weekdays[x] for x in picked)
        if covered / n >= SHARE and covered >= MIN_SUPPORT:
            names = "、".join(weekday_name(x) for x in sorted(picked))
            add("days", "schedule", f"通常在{names}练", f"完成 {n} 次，其中 {covered} 次在{names}")
            break

    # 每次大约多久：记了时长的至少 3 次，七成落在中位数上下 25% 以内
    minutes = [x.minutes for x in done if x.minutes]
    if len(minutes) >= MIN_SUPPORT:
        mid = statistics.median(minutes)
        near = sum(1 for m in minutes if abs(m - mid) <= mid * 0.25)
        if near / len(minutes) >= SHARE:
            shown = int(round(mid / 5) * 5)
            add(
                "minutes",
                "schedule",
                f"每次通常练 {shown} 分钟左右",
                f"记了时长的 {len(minutes)} 次里 {near} 次在 {shown} 分钟上下",
            )

    # 平均每周练几次（取整，减少来回变）
    per_week = round(n / (days / 7))
    if per_week >= 1:
        add("frequency", "schedule", f"每周大约练 {per_week} 次", f"完成 {n} 次")

    # 用力程度的习惯
    rpes = [x.rpe for x in done if x.rpe]
    if len(rpes) >= MIN_SUPPORT:
        low = sum(1 for r in rpes if r <= 6)
        high = sum(1 for r in rpes if r >= 8)
        if low / len(rpes) >= SHARE:
            add(
                "intensity",
                "preference",
                "训练时用力程度偏中低（感受多在 6 分及以下）",
                f"记了感受的 {len(rpes)} 次里 {low} 次在 6 分及以下",
            )
        elif high / len(rpes) >= SHARE:
            add(
                "intensity",
                "preference",
                "训练时常练到很吃力（感受多在 8 分及以上）",
                f"记了感受的 {len(rpes)} 次里 {high} 次在 8 分及以上",
            )

    # 计划里常跳过的动作（只算写了动作的记录）
    if plan is not None:
        with_items = [x for x in done if x.items]
        if len(with_items) >= MIN_SUPPORT:
            logged = Counter(it.exercise for x in with_items for it in x.items)
            weeks = days / 7
            want = Counter(it.exercise for s in plan.sessions for it in s.items)
            skipped = [
                name for name, per in want.items()
                if per * weeks >= MIN_SUPPORT and logged.get(name, 0) < per * weeks * SKIP_SHARE
            ]  # fmt: skip
            if skipped:
                names = "、".join(sorted(skipped))
                add(
                    "skips",
                    "preference",
                    f"计划里的{names}常跳过",
                    f"写了动作的 {len(with_items)} 次记录里很少出现{names}",
                )
    return out


def aspect_of(item: Item) -> str | None:
    m = _ASPECT.match(item.evidence)
    return m.group(1) if item.origin == "data" and m else None


def changes_for(
    existing: Sequence[Item], current: dict[str, Pref], recent: dict[str, Pref]
) -> list[Change]:
    """新算出的偏好 → 存储上的改动：新增、刷新（还被支持）、替换（新规律已稳定）。"""
    active = [x for x in existing if x.status == "active"]
    said_schedule = any(x.category == "schedule" and x.origin in ("said", "edited") for x in active)
    mine = {a: x for x in active if (a := aspect_of(x)) is not None}
    at = now()
    out: list[Change] = []
    for aspect, item in mine.items():
        if aspect in SCHEDULE_ASPECTS and said_schedule:  # 用户说过可练时间：以用户说的为准
            out.append(Change("status", id=item.id, status="superseded"))
    for aspect, p in current.items():
        if aspect in SCHEDULE_ASPECTS and said_schedule:
            continue
        old = mine.get(aspect)
        if old is not None and old.content == p.content:
            out.append(Change("status", id=old.id, status="active"))  # 还被数据支持：刷新时间
            continue
        if old is not None:
            again = recent.get(aspect)
            if again is None or again.content != p.content:
                continue  # 新规律最近 14 天还不稳定：先不替换，旧的不刷新，到期自然不用
            out.append(Change("status", id=old.id, status="superseded"))
        item = Item(new_id(), p.category, p.content, p.evidence, "data", "active", at, at,
                    old.id if old else None)  # fmt: skip
        out.append(Change("insert", item=item))
    return out


async def refresh(
    user_id: str, memory: MemoryStore, training: TrainingStore, today: date | None = None
) -> list[Change]:
    """按最新的训练记录更新偏好；暂停记忆时不更新。日志只记条数，不记内容。"""
    today = today or date.today()
    if await memory.paused(user_id):
        return []
    stored = await training.plan(user_id)
    logs = [x.log for x in await training.workouts(user_id, today - timedelta(days=WINDOW - 1))]
    plan = stored.plan if stored else None
    current = derive(logs, today, plan=plan)
    recent = derive(logs, today, days=RECENT, plan=plan, min_sessions=RECENT_MIN_SESSIONS,
                    min_span=RECENT_MIN_SPAN)  # fmt: skip
    changes = changes_for(await memory.items(user_id), current, recent)
    if changes:
        await memory.apply(user_id, changes)
    _log.info("prefs refreshed: derived=%d changes=%d", len(current), len(changes))
    return changes


_DONE: dict[str, date] = {}


def due(user_id: str, today: date | None = None) -> bool:
    """每天第一次回答之后更新一次（同一进程内）；打卡后不受这个限制。"""
    today = today or date.today()
    if _DONE.get(user_id) == today:
        return False
    _DONE[user_id] = today
    if len(_DONE) > 5000:
        _DONE.clear()
    return True
