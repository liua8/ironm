"""目标进度与阶段复测（spec [2026-10-23] §18 需求 6）：设目标体重和日期，按体重趋势预计达成日期。

- 起点：设目标时最新的体重（那时还没有体重记录，就用设目标之后的第一次）；当前：最新的体重；
- 预计达成日期 = 今天 + 还差多少 ÷ 每周变化（与数据页"体重每周变化"同一份计算）；体重记录不够两周时说明还缺什么；
- 预计比目标日期晚 2 周以上算落后、早 4 周以上算超前，只提示，改不改目标或计划由用户决定；
- 要按期达到时每周减重超过体重的 1%（K37）或增重超过 0.5%（经验），提示目标定得太快；
- 距上次复测（或设目标）满 4 周提醒复测体重、腰围和关键动作，满 6 周写明已经超过。
不调用模型；目标加密存储，日志不写内容。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Any, Literal, Protocol

from ironm_agent.metrics import Metric, Point

type Status = Literal["reached", "on_track", "behind", "ahead", "wrong_way", "unknown"]

RETEST_DAYS = 28
RETEST_LATE = 42
BEHIND_DAYS = 14
AHEAD_DAYS = 28
FAST_LOSS = 0.01
FAST_GAIN = 0.005
CLOSE = 0.2  # 差 0.2 公斤以内算达到


@dataclass(frozen=True)
class Goal:
    value: float  # 目标体重（公斤）
    by: date
    set_day: date
    start: float | None = None
    retest_day: date | None = None

    def json(self) -> dict[str, Any]:
        return {
            "kind": "weight",
            "value": self.value,
            "by": self.by.isoformat(),
            "set_day": self.set_day.isoformat(),
            "start": self.start,
            "retest_day": (self.retest_day or self.set_day).isoformat(),
        }

    @staticmethod
    def of(d: dict[str, Any]) -> Goal:
        return Goal(
            float(d["value"]),
            date.fromisoformat(d["by"]),
            date.fromisoformat(d["set_day"]),
            float(d["start"]) if d.get("start") is not None else None,
            date.fromisoformat(d["retest_day"]) if d.get("retest_day") else None,
        )


def _cn(d: date) -> str:
    return f"{d.year}年{d.month}月{d.day}日"


def _g(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".")


def start_of(goal: Goal, weights: Sequence[Point]) -> float | None:
    if goal.start is not None:
        return goal.start
    after = sorted(p for p in weights if p[0] >= goal.set_day)
    return after[0][1] if after else None


def progress(
    goal: Goal, weights: Sequence[Point], trend: Metric | None, today: date
) -> dict[str, Any]:
    pts = sorted(weights)
    current = pts[-1][1] if pts else None
    start = start_of(goal, pts)
    out: dict[str, Any] = {
        "name": "体重",
        "unit": "公斤",
        "start": start,
        "current": current,
        "target": goal.value,
        "by": goal.by.isoformat(),
        "predicted": None,
        "status": "unknown",
        "message": "",
        "missing": "",
        "pace": "",
        "retest": retest(goal, today),
    }
    if current is None:
        out["missing"] = "还没有体重记录：称一次体重后才能算进度。"
        return out
    need = goal.value - current
    toward = start is None or (start - goal.value) * (current - goal.value) > 0
    if abs(need) <= CLOSE or not toward:
        out["status"] = "reached"
        out["message"] = f"已经达到目标体重 {_g(goal.value)} 公斤：可以设一个新目标，或者转为保持。"
        return out
    days_left = (goal.by - today).days
    if days_left > 0:
        per_week = need / (days_left / 7)
        if per_week < 0 and -per_week > current * FAST_LOSS:
            out["pace"] = (
                f"要按期达到，每周得减 {-per_week:.2f} 公斤，超过体重的 1%（{current * FAST_LOSS:.2f} 公斤），"
                "减得太快容易丢肌肉：建议把日期往后放。"
            )
        elif per_week > 0 and per_week > current * FAST_GAIN:
            out["pace"] = (
                f"要按期达到，每周得增 {per_week:.2f} 公斤，超过体重的 0.5%（{current * FAST_GAIN:.2f} 公斤），"
                "可能多长脂肪：建议把日期往后放。"
            )
    if trend is None or trend.value is None:
        why = "；".join(trend.missing) if trend is not None and trend.missing else "体重记录"
        out["missing"] = f"体重记录还不够两周，算不出预计日期（还缺：{why}）。"
        return out
    slope = trend.value
    if trend.brief == "基本持平" or slope == 0:
        out["message"] = "体重这几周基本持平，按现在的趋势还看不出什么时候能达到。"
        out["status"] = "behind" if days_left <= 0 else "unknown"
        return out
    if slope * need < 0:
        out["status"] = "wrong_way"
        out["message"] = (
            f"体重这几周在往反方向变（每周 {slope:+.2f} 公斤）：可以看看计划和饮食要不要调整。"
        )
        return out
    predicted = today + timedelta(days=round(need / slope * 7))
    out["predicted"] = predicted.isoformat()
    late = (predicted - goal.by).days
    if days_left <= 0:
        out["status"] = "behind"
        out["message"] = (
            f"目标日期已经过了；按现在的速度预计 {_cn(predicted)} 达到：可以重新定个日期。"
        )
    elif late > BEHIND_DAYS:
        out["status"] = "behind"
        out["message"] = (
            f"按现在的速度预计 {_cn(predicted)} 达到，比目标日期晚约 {round(late / 7)} 周："
            "可以把日期往后放，或者调整计划和饮食，由你决定。"
        )
    elif -late > AHEAD_DAYS:
        out["status"] = "ahead"
        out["message"] = (
            f"按现在的速度预计 {_cn(predicted)} 达到，比目标日期早约 {round(-late / 7)} 周："
            "可以提前目标，或者放慢一点更稳妥，由你决定。"
        )
    else:
        out["status"] = "on_track"
        out["message"] = f"按现在的速度预计 {_cn(predicted)} 达到，和目标日期差不多。"
    return out


def retest(goal: Goal, today: date) -> dict[str, Any]:
    last = goal.retest_day or goal.set_day
    days = (today - last).days
    due = days >= RETEST_DAYS
    text = ""
    if due:
        late = "，已经超过 6 周" if days >= RETEST_LATE else ""
        text = (
            f"距上次复测 {days} 天{late}：建议复测一次体重、腰围和关键动作"
            "（比如深蹲、卧推能做的重量和次数）。"
        )
    return {"due": due, "days": days, "last": last.isoformat(), "text": text}


# ---- 存储 -----------------------------------------------------------------------------------


class GoalStore(Protocol):
    async def get(self, user_id: str) -> Goal | None: ...
    async def set(self, user_id: str, goal: Goal) -> None: ...
    async def clear(self, user_id: str) -> None: ...


class GoalBook:
    """内存版（测试用）。"""

    def __init__(self) -> None:
        self.rows: dict[str, Goal] = {}

    async def get(self, user_id: str) -> Goal | None:
        return self.rows.get(user_id)

    async def set(self, user_id: str, goal: Goal) -> None:
        self.rows[user_id] = goal

    async def clear(self, user_id: str) -> None:
        self.rows.pop(user_id, None)


DDL = """
CREATE TABLE IF NOT EXISTS ironm_goal (
    user_id    text PRIMARY KEY,
    content    text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
)
"""


class PgGoal:
    """数据库版：目标值、日期、起点合在 content 里，用 mirobody 的加密函数加密。"""

    def __init__(self) -> None:
        self._ready = False

    async def _q(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        from mirobody.utils.db import execute_query

        if not self._ready:
            await execute_query(DDL, {}, log_sql=False)
            self._ready = True
        rows = await execute_query(sql, params, log_sql=False)
        return rows if isinstance(rows, list) else []

    async def get(self, user_id: str) -> Goal | None:
        rows = await self._q(
            "SELECT decrypt_content(content) AS content FROM ironm_goal WHERE user_id = :uid",
            {"uid": user_id},
        )
        return Goal.of(json.loads(rows[0]["content"])) if rows else None

    async def set(self, user_id: str, goal: Goal) -> None:
        await self._q(
            "INSERT INTO ironm_goal (user_id, content) VALUES (:uid, encrypt_content(:content))"
            " ON CONFLICT (user_id) DO UPDATE SET content = EXCLUDED.content, updated_at = now()",
            {"uid": user_id, "content": json.dumps(goal.json(), ensure_ascii=False)},
        )

    async def clear(self, user_id: str) -> None:
        await self._q("DELETE FROM ironm_goal WHERE user_id = :uid", {"uid": user_id})


_default: GoalStore | None = None


def default_goal() -> GoalStore:
    global _default
    if _default is None:
        _default = PgGoal()
    return _default


def retested(goal: Goal, today: date) -> Goal:
    return replace(goal, retest_day=today)
