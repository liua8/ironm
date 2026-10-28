"""肌肉人体图：近 7 天每块肌肉练了多少组、哪些还在恢复、哪些没练（spec [2026-10-23] §13、§30）。
恢复怎么算见 recovery.py。

按训练记录和动作库的标注用规则计算，不调用模型。每个动作标了主要练到和辅助练到的细分肌肉：
主要练到的每组记 1 组，辅助练到的每组按半组算。深浅按近 7 天的组数分档，档位参照每周训练量
与增肌的剂量—效应关系（K04：每周 10 组以上明显好于不足 5 组）。只写了"完成"、没写动作的记录
（首页一键打卡），按那天计划里的动作算。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal

from ironm_agent import body
from ironm_agent.protools.movement import find
from ironm_agent.protools.recovery import Feel, Recovery, recovery
from ironm_agent.training import Plan, WorkoutLog

type Level = Literal["none", "low", "mid", "high"]
LEVEL_NAMES: dict[str, str] = {
    "none": "近 7 天没练",
    "low": "不到 5 组",
    "mid": "5–9 组",
    "high": "10 组以上",
}
ASSIST_WEIGHT = 0.5
WEEK_DAYS = 7
LOOKBACK_DAYS = 28

# 人体图上的细分肌肉：身体部位编码表里的 28 块（§57），按表里的顺序
MUSCLES: tuple[str, ...] = tuple(n.code for n in body.table().of_level("muscle"))


# 动作库里有动作主要练到的肌肉：只有这些才列进"近 7 天没练"（没有动作能补的不列）
def _trainable() -> frozenset[str]:
    from ironm_agent.protools.movement import moves

    return frozenset(m for mv in moves() for m in mv.tag.muscles)


def level(sets: float) -> Level:
    return "none" if sets <= 0 else "low" if sets < 5 else "mid" if sets < 10 else "high"


@dataclass
class Muscle:
    code: str  # 编码表里的细分肌肉
    sets_7d: float = 0
    last: date | None = None
    history: list[str] = field(default_factory=list)  # 最近几次：日期、动作、组数

    def json(self, today: date, rec: Recovery) -> dict[str, object]:
        sets = round(self.sets_7d * 2) / 2
        lv = level(sets)
        n = body.table().node(self.code)
        return {
            "code": self.code,
            "name": n.name,
            "formal": n.formal,
            "says": list(n.says[:3]),
            "model": list(n.model),
            "group": body.name(n.parent or ""),
            "part": next(a.name for a in body.table().ancestors(self.code) if a.level == "part"),
            "sets_7d": int(sets) if sets == int(sets) else sets,
            "level": lv,
            "level_name": LEVEL_NAMES[lv],
            "last": self.last.isoformat() if self.last else None,
            "history": self.history[:5],
            **rec.json(today),
        }  # fmt: skip


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
    logs: Sequence[WorkoutLog],
    today: date,
    plan: Plan | None = None,
    feels: dict[str, tuple[Feel, date]] | None = None,
) -> dict[str, object]:
    """logs 要包含今天往前约 32 天的训练（恢复要看"4 周内练过没有"）。"""
    muscles = {m: Muscle(m) for m in MUSCLES}
    start = today - timedelta(days=LOOKBACK_DAYS - 1)
    done = sorted(
        (x for x in logs if x.done and start <= x.day <= today), key=lambda x: x.day, reverse=True
    )
    for log in done:
        recent = (today - log.day).days < WEEK_DAYS
        per_muscle: dict[str, list[str]] = defaultdict(list)
        for name, sets in _done_items(log, plan):
            move = find(name)
            if move is None:
                continue
            for weight, names in ((1.0, move.tag.muscles), (ASSIST_WEIGHT, move.tag.assist)):
                for m in names:
                    item = muscles[m]
                    per_muscle[m].append(
                        f"{move.name} {sets} 组" + ("（辅助）" if weight < 1 else "")
                    )
                    if recent:
                        item.sets_7d += weight * sets
        for m, what in per_muscle.items():
            item = muscles[m]
            if item.last is None:
                item.last = log.day
            item.history.append(f"{log.day.month}月{log.day.day}日：" + "、".join(what))
    rec = recovery(logs, today, plan, _done_items, feels)
    out = [muscles[m].json(today, rec[m]) for m in MUSCLES]
    trainable = _trainable()
    return {
        "today": today.isoformat(),
        "muscles": out,
        "untrained": [x["name"] for x in out if x["level"] == "none" and x["code"] in trainable],
        "recovering": [x["name"] for x in out if x["recovering"]],
        "sessions": len(done),
        "note": "组数按近 7 天的训练记录算：主要练到的每组记 1 组，辅助练到的按半组；恢复按肌肉、动作、组数和"
        "用力程度估算，你说的感受优先。只记了'完成'的那次按当天计划算。",
    }
