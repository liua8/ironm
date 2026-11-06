"""目标进度与阶段复测（spec [2026-10-23] §18 需求 6）：设目标体重和日期，按体重趋势预计达成日期。

- 起点：设目标时最新的体重（那时还没有体重记录，就用设目标之后的第一次）；当前：最新的体重；
- 预计达成日期 = 今天 + 还差多少 ÷ 每周变化（与数据页"体重每周变化"同一份计算）；体重记录不够两周时说明还缺什么；
- 只给事实（§182）：每周变化（公斤和占体重的百分比）、预计哪天到、离目标日期几天、要按期到每周得变多少；
  落后、超前、定得太快不再由代码判断，交给管家看事实判断（回答里每周减重超过 1 公斤照旧由回答核对拦）；
- 距上次复测（或设目标）满 4 周提醒复测体重、腰围和关键动作，满 6 周写明已经超过。
不调用模型；目标加密存储，日志不写内容。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Any, Protocol

from ironm_agent.metrics import Metric, Point

RETEST_DAYS = 28
RETEST_LATE = 42
CLOSE = 0.2  # 差 0.2 公斤以内算达到


@dataclass(frozen=True)
class Goal:
    value: float  # 目标体重（公斤）
    by: date
    set_day: date
    start: float | None = None
    retest_day: date | None = None
    celebrated: date | None = None  # 达到目标后第一次看到、放过彩带的那天（§93）

    def json(self) -> dict[str, Any]:
        return {
            "kind": "weight",
            "value": self.value,
            "by": self.by.isoformat(),
            "set_day": self.set_day.isoformat(),
            "start": self.start,
            "retest_day": (self.retest_day or self.set_day).isoformat(),
            "celebrated": self.celebrated.isoformat() if self.celebrated else None,
        }

    @staticmethod
    def of(d: dict[str, Any]) -> Goal:
        return Goal(
            float(d["value"]),
            date.fromisoformat(d["by"]),
            date.fromisoformat(d["set_day"]),
            float(d["start"]) if d.get("start") is not None else None,
            date.fromisoformat(d["retest_day"]) if d.get("retest_day") else None,
            date.fromisoformat(d["celebrated"]) if d.get("celebrated") else None,
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
    """目标进度的事实（§182）：起点、当前、目标、变了多少、每周变化（公斤和占体重的百分比）、按现在的速度
    预计哪天到、离目标日期还有几天、要按期到每周得变多少、到了没有、还缺什么数据。不判断落后、超前、太快，
    这些交给管家看事实判断。"""
    pts = sorted(weights)
    current = pts[-1][1] if pts else None
    start = start_of(goal, pts)
    days_left = (goal.by - today).days
    out: dict[str, Any] = {
        "name": "体重",
        "unit": "公斤",
        "start": start,
        "current": current,
        "target": goal.value,
        "by": goal.by.isoformat(),
        "days_left": days_left,  # 离目标日期还有几天（负数是已经过了几天）
        "predicted": None,  # 按现在的速度预计哪天到
        "weekly": None,  # 体重每周变化（公斤，负数是减）
        "weekly_pct": None,  # 每周变化占现在体重的百分比
        "need_weekly": None,  # 要在目标日期前到，每周得变多少公斤
        "need_pct": None,
        "reached": False,
        "status": "unknown",  # reached / going / unknown：只是到没到、有没有数，不是判断
        "facts": [],  # 给人看的事实，一条一句
        "missing": "",
        "retest": retest(goal, today),
        "percent": None,  # 从起点到目标完成了百分之几（§93）
        "changed": None,  # 从起点到现在变了多少公斤（负数是减了）
        "celebrate": False,  # 达到目标、还没庆祝过
    }
    facts: list[str] = out["facts"]
    if current is not None and start is not None:
        out["changed"] = round(current - start, 1)
        span = goal.value - start
        if span:
            out["percent"] = max(0, min(100, round((current - start) / span * 100)))
    if current is None:
        out["missing"] = "还没有体重记录：称一次体重后才能算进度。"
        return out
    need = goal.value - current
    toward = start is None or (start - goal.value) * (current - goal.value) > 0
    if abs(need) <= CLOSE or not toward:
        out["status"] = "reached"
        out["reached"] = True
        facts.append(f"已经到了目标体重 {_g(goal.value)} 公斤（现在 {_g(current)} 公斤）。")
        out["percent"] = 100 if out["percent"] is not None else None
        out["celebrate"] = goal.celebrated is None
        return out
    out["status"] = "going"
    facts.append(
        f"离目标日期还有 {days_left} 天。"
        if days_left > 0
        else f"目标日期已经过了 {-days_left} 天。"
        if days_left < 0
        else "今天就是目标日期。"
    )
    if days_left > 0:
        per_week = need / (days_left / 7)
        out["need_weekly"] = round(per_week, 2)
        out["need_pct"] = round(per_week / current * 100, 2)
        facts.append(
            f"要在目标日期前到，每周要{'减' if per_week < 0 else '增'} {abs(per_week):.2f} 公斤"
            f"（现在体重的 {abs(per_week) / current * 100:.1f}%）。"
        )
    if trend is None or trend.value is None:
        why = "；".join(trend.missing) if trend is not None and trend.missing else "体重记录"
        out["missing"] = f"体重记录还不够两周，算不出每周变化和预计日期（还缺：{why}）。"
        return out
    slope = float(trend.value)
    out["weekly"] = round(slope, 2)
    out["weekly_pct"] = round(slope / current * 100, 2)
    facts.insert(0, f"最近体重每周 {slope:+.2f} 公斤（现在体重的 {slope / current * 100:+.1f}%）。")
    if trend.brief == "基本持平" or slope == 0:
        facts.append("按现在的速度算不出哪天到（体重基本持平）。")
        return out
    if slope * need < 0:
        facts.append("按现在的速度算不出哪天到（体重在往离目标更远的方向变）。")
        return out
    predicted = today + timedelta(days=round(need / slope * 7))
    out["predicted"] = predicted.isoformat()
    facts.append(f"按现在的速度预计 {_cn(predicted)} 到。")
    return out


def line(goal: Goal, snapshot: Any) -> str:
    """一句话说清目标（排新计划前确认、计划说明、档案里用，spec [2026-10-23] §55 需求 2）：只写事实（§182）
    "2027年10月26日前体重到 65 公斤，现在 67 公斤，每周 -0.30 公斤，按现在的速度预计 2027年9月1日到（10月26日设的）"。"""
    trend = next((m for m in snapshot.metrics if m.key == "weight_trend"), None)
    p = progress(goal, snapshot.readings.weight, trend, snapshot.today)
    parts = [f"{_cn(goal.by)}前体重到 {_g(goal.value)} 公斤"]
    if p["current"] is not None:
        parts.append(f"现在 {_g(p['current'])} 公斤")
    if p["reached"]:
        parts.append("已经到了")
    else:
        if p["weekly"] is not None:
            parts.append(f"每周 {p['weekly']:+.2f} 公斤")
        if p["predicted"]:
            parts.append(f"按现在的速度预计 {_cn(date.fromisoformat(p['predicted']))}到")
    return "，".join(parts) + f"（{goal.set_day.month}月{goal.set_day.day}日设的）"


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
