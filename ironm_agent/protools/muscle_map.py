"""肌肉人体图：近期练了哪些肌肉、哪些没练（spec [2026-10-23] §13）。

按训练记录和动作库的标注用规则计算，不调用模型。只写了"完成"、没写动作的记录（首页一键打卡），
按那天计划里的动作算。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal

from ironm_agent.protools.movement import find
from ironm_agent.training import Plan, WorkoutLog

type Status = Literal["recent", "week", "none"]
STATUS_NAMES: dict[str, str] = {"recent": "两天内练过", "week": "本周练过", "none": "7 天以上没练"}
RECENT_DAYS = 2
WEEK_DAYS = 7
LOOKBACK_DAYS = 28

# 人体图上的肌群：正面、背面各一张（肩在两面都有）
FRONT = ("胸", "肩", "肱二头肌", "核心", "股四头肌")
BACK = ("背", "肩", "肱三头肌", "臀", "腘绳肌", "小腿")
GROUPS: tuple[str, ...] = tuple(dict.fromkeys((*FRONT, *BACK)))


@dataclass
class Group:
    name: str
    status: Status = "none"
    last: date | None = None
    sets_7d: int = 0
    history: list[str] = field(default_factory=list)  # 最近几次：日期、动作、组数

    def json(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "status_name": STATUS_NAMES[self.status],
            "last": self.last.isoformat() if self.last else None,
            "sets_7d": self.sets_7d,
            "history": self.history[:5],
        }


def _done_items(log: WorkoutLog, plan: Plan | None) -> list[tuple[str, int]]:
    """这次训练做了哪些动作、几组；没写动作时按那天计划里的动作算。"""
    if log.items:
        return [(x.exercise, x.sets or 1) for x in log.items]
    if plan is None:
        return []
    session = next((s for s in plan.sessions if log.session and s.name == log.session), None)
    session = session or plan.session_on(log.day)
    return [(x.exercise, x.sets) for x in session.items] if session else []


def muscle_map(
    logs: Sequence[WorkoutLog], today: date, plan: Plan | None = None
) -> dict[str, object]:
    groups = {g: Group(g) for g in GROUPS}
    start = today - timedelta(days=LOOKBACK_DAYS - 1)
    done = sorted(
        (x for x in logs if x.done and start <= x.day <= today), key=lambda x: x.day, reverse=True
    )
    for log in done:
        per_group: dict[str, list[str]] = defaultdict(list)
        for name, sets in _done_items(log, plan):
            move = find(name)
            if move is None:
                continue
            for g in move.tag.groups:
                if g not in groups:
                    continue
                per_group[g].append(f"{move.name} {sets} 组")
                if (today - log.day).days < WEEK_DAYS:
                    groups[g].sets_7d += sets
        for g, what in per_group.items():
            item = groups[g]
            if item.last is None:
                item.last = log.day
            item.history.append(f"{log.day.month}月{log.day.day}日：" + "、".join(what))
    for item in groups.values():
        if item.last is None:
            continue
        ago = (today - item.last).days
        item.status = "recent" if ago <= RECENT_DAYS else "week" if ago < WEEK_DAYS else "none"
    untrained = [g for g in GROUPS if groups[g].status == "none"]
    return {
        "today": today.isoformat(),
        "front": [groups[g].json() for g in FRONT],
        "back": [groups[g].json() for g in BACK],
        "untrained": untrained,
        "sessions": len(done),
        "note": "按最近 28 天的训练记录和动作库的标注计算；只记了'完成'的那次按当天计划里的动作算。",
    }
