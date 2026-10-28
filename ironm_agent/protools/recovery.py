"""每块肌肉的恢复（spec [2026-10-23] §30）：练后大约几天能再练这块肌肉，并写明原因。

按规则计算，不调用模型。只有主要练到的肌肉才算恢复，辅助练到的不算。
- 底数：同一肌群两次训练至少隔 48 小时（K48）；有训练基础时上肢一般 24 小时以内、下肢 48–72 小时，
  多关节、在肌肉拉长位置发力的动作更慢（K49、K50、K54）。日常用得多的小腿、核心、臀中肌、前锯肌、颈部按 1 天
  （由 K52"损伤和日常使用程度有关"推出，没有直接研究）。
- 加天数：接近力竭（K51）、当次组数多（K55）、4 周内没练过这块肌肉（K52、K53，手臂多加一天）。
- 封顶 4 天；本人说"还酸""不酸了"优先（个体差异大，K49）。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal

from ironm_agent.protools.movement import find
from ironm_agent.training import Plan, WorkoutLog

type Feel = Literal["sore", "fine"]

# 键是身体部位编码表里的细分肌肉（§57 需求 2：28 块按原来的分组给天数）
BASE_DAYS: dict[str, int] = {
    "muscle.quadriceps": 2, "muscle.glute_max": 2, "muscle.adductors": 2, "muscle.hamstrings": 2,
    "muscle.erector_spinae": 2, "muscle.hip_flexors": 2,
    "muscle.pec_major_upper": 1, "muscle.pec_major_lower": 1, "muscle.lats": 1, "muscle.upper_traps": 1,
    "muscle.mid_lower_traps": 1, "muscle.rhomboids": 1, "muscle.anterior_delt": 1, "muscle.lateral_delt": 1,
    "muscle.posterior_delt": 1, "muscle.rotator_cuff": 1, "muscle.biceps": 1, "muscle.brachialis": 1,
    "muscle.triceps": 1, "muscle.forearms": 1,
    "muscle.gastrocnemius": 1, "muscle.soleus": 1, "muscle.tibialis_anterior": 1, "muscle.glute_med": 1,
    "muscle.rectus_abdominis": 1, "muscle.obliques": 1, "muscle.serratus_anterior": 1, "muscle.neck": 1,
}  # fmt: skip
BASE_WHY: dict[int, str] = {2: "下肢多关节动作，约 48 小时", 1: "上肢，约 24 小时"}
# 日常用得多的：按 1 天，原因另写
DAILY = frozenset({
    "muscle.gastrocnemius", "muscle.soleus", "muscle.tibialis_anterior", "muscle.glute_med",
    "muscle.rectus_abdominis", "muscle.obliques", "muscle.serratus_anterior", "muscle.neck",
})  # fmt: skip
LENGTHENED = frozenset({"hinge"})  # 硬拉、罗马尼亚硬拉、壶铃摇摆：腘绳肌在拉长位置发力
ARMS = frozenset({"muscle.biceps", "muscle.brachialis", "muscle.triceps", "muscle.forearms"})
NEAR_FAILURE_RPE = 9
BIG_SETS = 8
UNACCUSTOMED_DAYS = 28
MAX_DAYS = 4
SORE_TOO_LONG_DAYS = 7  # 说酸超过一周：可能不只是练后酸痛（K08）
SORE_FORGET_DAYS = 14  # 说酸之后两周没再说：不再按"还酸"算

type ItemsOf = Callable[[WorkoutLog, Plan | None], list[tuple[str, int]]]


@dataclass
class Session:
    day: date
    sets: int = 0
    lengthened: bool = False
    rpe: int | None = None


@dataclass
class Recovery:
    muscle: str
    ready_on: date | None = None  # 哪天可以再练；None 表示近期没主要练过
    days: int = 0
    why: list[str] = field(default_factory=list)
    trained_on: date | None = None
    feel: Feel | None = None
    sore_too_long: bool = False

    def state(self, today: date) -> str:
        if self.feel == "sore":
            return "sore"
        if self.ready_on is None or self.ready_on <= today:
            return "ready"
        return "today" if self.trained_on == today else "recovering"

    def json(self, today: date) -> dict[str, object]:
        state = self.state(today)
        return {
            "state": state,
            "recovering": state != "ready",
            "ready_on": self.ready_on.isoformat() if self.ready_on and state != "ready" else None,
            "recover_days": self.days,
            "recover_why": self.why,
            "trained_on": self.trained_on.isoformat() if self.trained_on else None,
            "sore_too_long": self.sore_too_long,
        }


def _main_sessions(
    logs: Sequence[WorkoutLog], plan: Plan | None, items_of: ItemsOf
) -> dict[str, list[Session]]:
    """每块肌肉作为主要肌肉练过的每次训练（按日期从新到旧）。"""
    out: dict[str, list[Session]] = {}
    for log in sorted((x for x in logs if x.done), key=lambda x: x.day, reverse=True):
        per: dict[str, Session] = {}
        for name, sets in items_of(log, plan):
            move = find(name)
            if move is None:
                continue
            for m in move.tag.muscles:
                s = per.setdefault(m, Session(log.day, rpe=log.rpe))
                s.sets += sets
                s.lengthened |= m == "muscle.hamstrings" and move.tag.pattern in LENGTHENED
        for m, s in per.items():
            out.setdefault(m, []).append(s)
    return out


def _need(muscle: str, s: Session, earlier: list[Session]) -> tuple[int, list[str]]:
    days = BASE_DAYS[muscle]
    daily = muscle in DAILY
    why = ["日常用得多，约 24 小时" if daily else BASE_WHY[days]]
    if s.lengthened:
        days += 1
        why[0] = "硬拉类动作在拉长位置发力，约 72 小时"
    if s.rpe is not None and s.rpe >= NEAR_FAILURE_RPE:
        days += 1
        why.append(f"感受 {s.rpe} 分，接近力竭")
    if s.sets >= BIG_SETS:
        days += 1
        why.append(f"当次练了 {s.sets} 组")
    if not any(0 < (s.day - e.day).days <= UNACCUSTOMED_DAYS for e in earlier):
        extra = 2 if muscle in ARMS else 1
        days += extra
        why.append("4 周内没练过，不习惯" + ("，手臂更容易酸" if extra == 2 else ""))
    if days > MAX_DAYS:
        why.append(f"最多按 {MAX_DAYS} 天算")
    return min(days, MAX_DAYS), why


def recovery(
    logs: Sequence[WorkoutLog],
    today: date,
    plan: Plan | None,
    items_of: ItemsOf,
    feels: dict[str, tuple[Feel, date]] | None = None,
) -> dict[str, Recovery]:
    """logs 要包含今天往前至少 4 + 28 天的训练，才能判断"4 周内没练过"。"""
    feels = feels or {}
    sessions = _main_sessions(logs, plan, items_of)
    out: dict[str, Recovery] = {}
    for muscle in BASE_DAYS:
        r = Recovery(muscle)
        mine = sessions.get(muscle, [])
        for i, s in enumerate(mine):
            if (today - s.day).days > MAX_DAYS:
                break
            days, why = _need(muscle, s, mine[i + 1 :])
            ready = s.day + timedelta(days=days)
            if r.ready_on is None or ready > r.ready_on:
                r.ready_on, r.days, r.why, r.trained_on = ready, days, why, s.day
        feel = feels.get(muscle)
        if feel is not None and (today - feel[1]).days > SORE_FORGET_DAYS:
            feel = None
        if feel is not None and (r.trained_on is None or feel[1] >= r.trained_on):
            kind, said = feel
            if kind == "sore":
                r.feel = "sore"
                r.why = [*r.why, f"{said.month}月{said.day}日说还酸"]
                r.sore_too_long = (today - said).days >= SORE_TOO_LONG_DAYS
            elif r.ready_on is not None and r.ready_on > today:
                r.feel = "fine"
                r.ready_on = today
                r.why = [*r.why, f"{said.month}月{said.day}日说已经不酸了"]
        out[muscle] = r
    return out
