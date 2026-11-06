"""首页的今日简报与每周复盘（spec [2026-10-23] §10）：只给事实，打开首页就能看到，不调用模型。

- 今日简报：今天按计划练什么、今日营养目标、一条最该注意的安全提醒；身体状态不由代码定级，
  今天怎么练看管家的"今天"（§163、§182）；
- 每周复盘：本周（周一到今天）计划完成几次、体重变化、平均睡眠、静息心率与心率变异性的变化；
  要不要调、怎么调由管家复盘提，代码不再给规则建议（§182）。
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import date
from typing import Any

from ironm_agent.casefile import Snapshot, readiness, risks
from ironm_agent.memory_store import Item
from ironm_agent.metrics import Metric
from ironm_agent.training import Plan, WorkoutLog, week_of, week_start, weekday_name


def _metric(metrics: Sequence[Metric], key: str) -> Metric | None:
    return next((m for m in metrics if m.key == key and m.value is not None), None)


def _fmt(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".")


def today_brief(
    snap: Snapshot, memory: Sequence[Item], plan: Plan | None, logs: Sequence[WorkoutLog]
) -> dict[str, Any]:
    today = snap.today
    state = readiness(snap.readings, "", today)
    found = risks(snap.readings, memory, today)
    session = plan.session_on(today) if plan else None
    done = any(x.day == today and x.done for x in logs)
    training: dict[str, Any]
    if plan is None:
        training = {"kind": "no_plan", "text": "还没有训练计划：让教练按你的目标和器械排一份。"}
    elif session is None:
        training = {
            "kind": "rest",
            "text": f"今天（{weekday_name(today.isoweekday())}）按计划休息，可以散步或拉伸。",
        }
    else:
        tip = ""
        if any(x.block for x in found):  # 安全护栏：危急指标
            tip = "先别练，等血压降下来、医生同意再说。"  # 状态差不再由规则建议减半、休息（§163），看管家的"今天"
        training = {
            "kind": "session",
            "name": session.name,
            "minutes": session.minutes,
            "items": [x.line() for x in session.items],
            "done": done,
            "tip": tip,
        }
    kcal, protein = _metric(snap.metrics, "kcal_target"), _metric(snap.metrics, "protein_target")
    if found:
        alert = found[0].note
    elif not state.current:
        alert = "连接手表或导入苹果健康的最新数据，管家就能看到你最近的睡眠和心率。"
    else:
        alert = ""
    return {
        "date": today.isoformat(),
        "weekday": weekday_name(today.isoweekday()),
        "body": list(state.facts),  # 今天的身体数据：数值和与他自己平时的差，不定级（§182）
        "training": training,
        "nutrition": {
            "kcal": kcal.value if kcal else None,
            "protein": protein.display
            or (_fmt(protein.value) if protein and protein.value else None)
            if protein
            else None,
        },
        "alert": alert,
    }


def weekly_review(
    snap: Snapshot,
    plan: Plan | None,
    logs: Sequence[WorkoutLog],
    since: date | None = None,
    *,
    sick: Collection[date] = (),
) -> dict[str, Any]:
    """sick：生病的日子（不算应练）。只给事实（§182）：规则的建议（减到几天、整体七成、少吃 200 千卡）去掉了。"""
    today = snap.today
    week = week_of(plan, logs, today, since, sick)
    weight = _metric(snap.metrics, "weight_trend")
    sleep = _metric(snap.metrics, "sleep")
    rhr = _metric(snap.metrics, "resting_hr")
    hrv = _metric(snap.metrics, "hrv_sdnn") or _metric(snap.metrics, "hrv_rmssd")
    return {
        "from": week_start(today).isoformat(),
        "to": today.isoformat(),
        "planned": week.planned,
        "due": week.due,
        "done": week.done,
        "sessions": [
            {"day": weekday_name(s.day), "name": s.name, "done": d} for s, d in week.sessions
        ],
        "weight": {"value": weight.value, "text": weight.text, "brief": weight.brief}
        if weight
        else None,
        "sleep": {"value": sleep.value, "brief": sleep.brief} if sleep else None,
        "resting_hr": {"value": rhr.value, "brief": rhr.brief} if rhr else None,
        "hrv": {"name": hrv.name, "value": hrv.value, "brief": hrv.brief} if hrv else None,
    }


def hero_line(today: dict[str, Any], week: dict[str, Any]) -> dict[str, str]:
    """首页"今日战报"的大标题和一句鼓劲的话（spec [2026-10-23] §19）：按规则，不调用模型。"""
    t = today.get("training") or {}
    planned, done = week.get("planned") or 0, week.get("done") or 0
    week_won = bool(planned) and done >= planned
    kind = t.get("kind")
    if kind == "session" and t.get("done"):
        return {
            "title": f"{t['name']} 已拿下",
            "push": "今天的训练完成了，干得漂亮！好好吃饭、早点睡。",
        }
    if kind == "session":
        if week_won:
            return {"title": f"今天练{t['name']}", "push": "本周目标已经达成，这一练是额外加分！"}
        return {
            "title": f"今天练{t['name']}",
            "push": f"{t.get('minutes', 45)} 分钟，练完就点亮今天，冲！",
        }
    if kind == "rest":
        if week_won:
            return {"title": "休息日", "push": "本周目标已经拿下，今天专心恢复。"}
        return {"title": "休息日", "push": "恢复也是训练的一部分：散散步、拉拉伸。"}
    return {"title": "开练吧", "push": "还没有训练计划：让教练按你的目标排一份，从今天开始。"}


# 首页一句鼓励的话（spec [2026-10-23] §34）：只鼓劲、不安排任务；按今天的情况选，没有特别情况时按日期轮换
CHEERS = (
    "每一次打卡，都在为更好的自己加分。",
    "动起来，比完美的计划更重要。",
    "坚持的人，身体都看得见。",
    "今天流的汗，是明天的底气。",
    "不求一次练很猛，只求每周都在练。",
    "比昨天的自己多一点，就是进步。",
    "身体会记住你的每一次坚持。",
)


def cheer(today: dict[str, Any], week: dict[str, Any], *, rainy: bool = False, hot: bool = False,
          on: date | None = None) -> str:  # fmt: skip
    t = today.get("training") or {}
    planned, done = week.get("planned") or 0, week.get("done") or 0
    kind = t.get("kind")
    if kind == "session" and t.get("done"):
        return "今天的训练完成了，干得漂亮！"
    if planned and done >= planned:
        return "本周目标已经拿下，接下来每一练都是加分。"
    if kind == "session" and rainy:
        return "下雨也挡不住你，室内一样练出汗。"
    if kind == "session" and hot:
        return "天热也在坚持，练聪明一点，比练得狠更重要。"
    if kind == "rest":
        return "休息也是进步的一部分，养足精神明天再来。"
    if kind not in ("session", "rest"):
        return "第一步最难，今天就迈出去。"
    if done >= 2:
        return f"这周已经练了 {done} 次，保持住这股劲！"
    day = on or date.today()
    return CHEERS[day.toordinal() % len(CHEERS)]
