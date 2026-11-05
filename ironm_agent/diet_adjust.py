"""两周饮食复盘（spec [2026-10-23] §18 需求 2）：按体重趋势用规则提出热量调整，用户确认后保存，可以撤销。

- 减脂：体重几周没下降，每天少吃约 200 千卡；掉得比每周体重的 1% 还快（K37），每天加回约 150 千卡；
- 增肌：体重没上升，每天多吃约 150 千卡；涨得比每周体重的 0.5% 还快，每天少吃约 150 千卡（经验）；
- 调整后的目标不低于基础代谢与女 1200、男 1500 千卡；累计调整不超过 ±500；距上次调整不到 14 天不再调整。
调整量和原因加密存储；日志不写内容。
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal, Protocol

from ironm_agent.metrics import KcalAdjust, Metric, Profile, safe_floor

CUT = 200
ADD = 150
MAX_TOTAL = 500
COOLDOWN_DAYS = 14
FAST_LOSS = 0.01  # 每周掉体重的 1% 以上算太快（K37 建议每周 0.5–1%）
FAST_GAIN = 0.005  # 增肌每周涨体重的 0.5% 以上算太快（经验）


# 按实际估消耗（spec [2026-10-23] §118 需求 7）
OBSERVE_DAYS = 14
MIN_LOGGED_DAYS = 10  # 至少这么多天记了
MIN_MEALS = 2  # 每天至少记了几餐才算这天记了
MIN_WEIGHINS = 6
MIN_SPAN = 10  # 称重的跨度至少几天
KCAL_PER_KG = 7700  # 每公斤体重约 7700 千卡，粗算（经验）
GAP = 300  # 和公式算的差这么多才提议
MIN_STEP = 50  # 被基础代谢和安全下限卡住、只剩几十千卡以内的变化：不提（两周模拟 11-05：每天建议少吃 4–6 千卡）


@dataclass(frozen=True)
class Observed:
    """按记的吃和体重变化估的每天实际消耗。"""

    tdee: int
    intake: int  # 记了的那些天平均每天吃的
    kg_per_week: float
    days: int  # 记了几天
    weighins: int


def by_day(rows: Sequence[Any]) -> dict[date, tuple[int, float]]:
    """饮食记录（meals.StoredMeal）→ 每天记了几餐、一共多少千卡。"""
    days: dict[date, tuple[int, float]] = {}
    for r in rows:
        n, k = days.get(r.day, (0, 0.0))
        days[r.day] = (n + 1, k + r.meal.macros.kcal)
    return days


def observed(
    day_kcal: dict[date, tuple[int, float]], weights: Sequence[tuple[date, float]], today: date
) -> tuple[Observed | None, str]:
    """day_kcal：每天记了几餐、一共多少千卡。条件不够时返回还差什么。"""
    start = today.toordinal() - OBSERVE_DAYS + 1
    logged = [
        k
        for d, (n, k) in day_kcal.items()
        if start <= d.toordinal() <= today.toordinal() and n >= MIN_MEALS
    ]
    pts = sorted((d, w) for d, w in weights if start <= d.toordinal() <= today.toordinal())
    span = (pts[-1][0] - pts[0][0]).days if pts else 0
    lack = []
    if len(logged) < MIN_LOGGED_DAYS:
        lack.append(
            f"最近 {OBSERVE_DAYS} 天里每天记 {MIN_MEALS} 餐以上的有 {len(logged)} 天，要 {MIN_LOGGED_DAYS} 天"
        )
    if len(pts) < MIN_WEIGHINS or span < MIN_SPAN:
        lack.append(
            f"同期称了 {len(pts)} 次体重、跨 {span} 天，要 {MIN_WEIGHINS} 次、跨 {MIN_SPAN} 天以上"
        )
    if lack:
        return None, "；".join(lack)
    xs = [d.toordinal() for d, _ in pts]
    ys = [w for _, w in pts]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sum(
        (x - mx) ** 2 for x in xs
    )
    intake = sum(logged) / len(logged)
    tdee = round(intake - slope * KCAL_PER_KG)
    return Observed(tdee, round(intake), round(slope * 7, 2), len(logged), len(pts)), ""


@dataclass(frozen=True)
class Proposal:
    delta: int  # 这次在现有调整量上再加多少
    total: int  # 调整后的总调整量
    before: int  # 调整前的每日热量目标
    after: int  # 调整后的每日热量目标
    reason: str
    basis: str  # 用了哪些数据


def _metric(metrics: Sequence[Metric], key: str) -> Metric | None:
    return next((m for m in metrics if m.key == key), None)


def propose(
    metrics: Sequence[Metric],
    profile: Profile,
    current: KcalAdjust | None,
    today: date,
    seen: Observed | None = None,
) -> tuple[Proposal | None, str]:
    """返回调整方案，或者为什么这次不调整。有按实际估的消耗、和公式差得多时先按它（§118）。"""
    if profile.goal not in ("fat_loss", "muscle"):
        return None, "目标是减脂或增肌时，才按体重趋势调整热量。"
    target, bmr, trend, weight = (
        _metric(metrics, k) for k in ("kcal_target", "bmr", "weight_trend", "weight")
    )
    if target is None or target.value is None or bmr is None or bmr.value is None:
        return None, "还算不出每日热量目标：先在个人中心填好身高、出生日期、性别和活动水平。"
    if current is not None and (today - current.since).days < COOLDOWN_DAYS:
        return (
            None,
            f"上次调整在 {current.since.month}月{current.since.day}日，两周后再看体重趋势。",
        )
    total_burn = _metric(metrics, "tdee")
    if seen is not None and total_burn is not None and total_burn.value:
        diff = seen.tdee - round(total_burn.value)
        if abs(diff) >= GAP:
            delta = min(ADD, diff) if diff > 0 else -min(CUT, -diff)
            reason = (f"按你记的吃和体重变化，每天实际消耗约 {seen.tdee} 千卡，"
                      f"比公式算的 {round(total_burn.value)} 千卡{'高' if diff > 0 else '低'} {abs(diff)} 千卡")  # fmt: skip
            basis = (f"最近 {seen.days} 天平均每天吃 {seen.intake} 千卡；体重每周 {seen.kg_per_week:+.2f} 公斤"
                     f"（称了 {seen.weighins} 次）；每公斤约 {KCAL_PER_KG} 千卡粗算")  # fmt: skip
            return _apply(delta, reason, basis, target.value, bmr.value, profile, current)
    if trend is None or trend.value is None or weight is None or weight.value is None:
        why = "；".join(trend.missing) if trend is not None and trend.missing else "体重记录"
        return None, f"体重记录还不够，看不出趋势（还缺：{why}）。"
    w, wk = weight.value, trend.value
    basis = f"{trend.text}；最新体重 {w:g} 公斤"
    delta = 0
    if profile.goal == "fat_loss":
        if trend.brief in ("基本持平", "在上升"):
            delta, reason = -CUT, "减脂期体重这几周没有下降"
        elif -wk > w * FAST_LOSS:
            delta = ADD
            reason = f"体重每周掉 {-wk:.2f} 公斤，超过体重的 1%（{w * FAST_LOSS:.2f} 公斤），掉得太快容易丢肌肉"
    elif trend.brief in ("基本持平", "在下降"):
        delta, reason = ADD, "增肌期体重这几周没有上升"
    elif wk > w * FAST_GAIN:
        delta = -ADD
        reason = (
            f"体重每周涨 {wk:.2f} 公斤，超过体重的 0.5%（{w * FAST_GAIN:.2f} 公斤），可能多长了脂肪"
        )
    if not delta:
        return None, "体重变化在合适的范围内，这两周不用调整热量。"
    return _apply(delta, reason, basis, target.value, bmr.value, profile, current)


def _apply(
    delta: int, reason: str, basis: str, target_now: float, bmr: float, profile: Profile,
    current: KcalAdjust | None,
) -> tuple[Proposal | None, str]:  # fmt: skip
    """在现有调整量上加 delta：累计不超过 ±500，不低于基础代谢和安全下限。"""
    now_total = current.kcal if current else 0
    total = max(-MAX_TOTAL, min(MAX_TOTAL, now_total + delta))
    if total == now_total:
        return None, f"累计调整已经到了 ±{MAX_TOTAL} 千卡的上限，建议先找营养师看看。"
    before = round(target_now)
    formula = before - now_total  # 公式算出的目标（不含调整量）
    after = round(max(formula + total, safe_floor(bmr, profile)))
    if abs(after - before) < MIN_STEP or (after - before) * delta < 0:  # 只剩几十千卡、或者被下限推成反方向：不提
        return None, "热量目标已经到了基础代谢和安全下限，不能再减；可以多活动或找营养师看看。"
    return Proposal(after - before, after - formula, before, after, reason, basis), ""


# ---- 存储 -----------------------------------------------------------------------------------

type State = Literal["active", "superseded", "undone"]


@dataclass(frozen=True)
class Stored:
    id: str
    adjust: KcalAdjust
    state: State
    created: datetime


class DietStore(Protocol):
    async def current(self, user_id: str) -> KcalAdjust | None: ...
    async def apply(self, user_id: str, adjust: KcalAdjust) -> None: ...
    async def undo(self, user_id: str) -> KcalAdjust | None: ...


class DietBook:
    """内存版（测试用）。"""

    def __init__(self) -> None:
        self.rows: dict[str, list[Stored]] = {}

    async def current(self, user_id: str) -> KcalAdjust | None:
        return next(
            (x.adjust for x in reversed(self.rows.get(user_id, [])) if x.state == "active"), None
        )

    async def apply(self, user_id: str, adjust: KcalAdjust) -> None:
        rows = self.rows.setdefault(user_id, [])
        rows[:] = [
            Stored(x.id, x.adjust, "superseded" if x.state == "active" else x.state, x.created)
            for x in rows
        ]
        rows.append(Stored(uuid.uuid4().hex, adjust, "active", datetime.now().astimezone()))

    async def undo(self, user_id: str) -> KcalAdjust | None:
        """撤销最近一次调整，回到上一次（没有上一次就是不调整）；返回撤销后的调整量。"""
        rows = self.rows.get(user_id, [])
        i = next((k for k in range(len(rows) - 1, -1, -1) if rows[k].state == "active"), None)
        if i is None:
            return None
        rows[i] = Stored(rows[i].id, rows[i].adjust, "undone", rows[i].created)
        j = next((k for k in range(i - 1, -1, -1) if rows[k].state == "superseded"), None)
        if j is not None:
            rows[j] = Stored(rows[j].id, rows[j].adjust, "active", rows[j].created)
            return rows[j].adjust
        return None


DDL = """
CREATE TABLE IF NOT EXISTS ironm_diet_adjust (
    id         text PRIMARY KEY,
    user_id    text NOT NULL,
    content    text NOT NULL,
    state      text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
)
"""


class PgDiet:
    """数据库版：调整量、起始日期和原因合在 content 里，用 mirobody 的加密函数加密。"""

    def __init__(self) -> None:
        self._ready = False

    async def _q(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        from mirobody.utils.db import execute_query

        if not self._ready:
            await execute_query(DDL, {}, log_sql=False)
            self._ready = True
        rows = await execute_query(sql, params or {}, log_sql=False)
        return rows if isinstance(rows, list) else []

    @staticmethod
    def _adjust(content: str) -> KcalAdjust:
        import json

        d = json.loads(content)
        return KcalAdjust(int(d["kcal"]), date.fromisoformat(d["since"]), str(d["reason"]))

    async def current(self, user_id: str) -> KcalAdjust | None:
        rows = await self._q(
            "SELECT decrypt_content(content) AS content FROM ironm_diet_adjust"
            " WHERE user_id = :uid AND state = 'active' ORDER BY created_at DESC LIMIT 1",
            {"uid": user_id},
        )
        return self._adjust(rows[0]["content"]) if rows else None

    async def apply(self, user_id: str, adjust: KcalAdjust) -> None:
        import json

        content = json.dumps({"kcal": adjust.kcal, "since": adjust.since.isoformat(), "reason": adjust.reason},
                             ensure_ascii=False)  # fmt: skip
        await self._q(
            "WITH old AS (UPDATE ironm_diet_adjust SET state = 'superseded'"
            " WHERE user_id = :uid AND state = 'active' RETURNING id)"
            " INSERT INTO ironm_diet_adjust (id, user_id, content, state)"
            " VALUES (:id, :uid, encrypt_content(:content), 'active')",
            {"id": uuid.uuid4().hex, "uid": user_id, "content": content},
        )

    async def undo(self, user_id: str) -> KcalAdjust | None:
        rows = await self._q(
            "SELECT id, state, decrypt_content(content) AS content, created_at FROM ironm_diet_adjust"
            " WHERE user_id = :uid AND state IN ('active', 'superseded') ORDER BY created_at DESC LIMIT 2",
            {"uid": user_id},
        )
        if not rows or rows[0]["state"] != "active":
            return None
        await self._q(
            "UPDATE ironm_diet_adjust SET state = 'undone' WHERE id = :id", {"id": rows[0]["id"]}
        )
        if len(rows) > 1:
            await self._q(
                "UPDATE ironm_diet_adjust SET state = 'active' WHERE id = :id",
                {"id": rows[1]["id"]},
            )
            return self._adjust(rows[1]["content"])
        return None


_default: DietStore | None = None


def default_diet() -> DietStore:
    global _default
    if _default is None:
        _default = PgDiet()
    return _default
