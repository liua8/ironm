"""首页的今日简报与每周复盘（spec [2026-10-23] §10）：全部用规则生成，打开首页就能看到，不调用模型。

- 今日简报：今天的身体状态、今天按计划练什么（状态差时建议改成轻松版或休息）、今日营养目标、一条最该注意的提醒；
- 每周复盘：本周（周一到今天）计划完成几次、体重变化、平均睡眠、静息心率与心率变异性的变化，按规则给 1–3 条建议。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

from ironm_agent.casefile import Snapshot, readiness, risks
from ironm_agent.memory_store import Item
from ironm_agent.metrics import Metric
from ironm_agent.training import Plan, WorkoutLog, week_of, week_start, weekday_name

MAX_TIPS = 3


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
        if any(x.block for x in found):
            tip = "先别练，等血压降下来、医生同意再说。"
        elif state.level == "poor":
            tip = "今天状态不好，建议改成轻松版（重量减轻、组数减半）或休息。"
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
    elif state.level == "poor":
        alert = "今天" + "；".join(state.reasons[:2]) + "：优先休息和睡眠。"
    elif state.level == "unknown":
        alert = "连接手表或导入苹果健康的最新数据，这里就能判断你今天的状态。"
    else:
        alert = ""
    return {
        "date": today.isoformat(),
        "weekday": weekday_name(today.isoweekday()),
        "readiness": {"level": state.level, "name": state.name, "reasons": list(state.reasons)},
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
    snap: Snapshot, plan: Plan | None, logs: Sequence[WorkoutLog], since: date | None = None
) -> dict[str, Any]:
    today = snap.today
    week = week_of(plan, logs, today, since)
    weight = _metric(snap.metrics, "weight_trend")
    sleep = _metric(snap.metrics, "sleep")
    rhr = _metric(snap.metrics, "resting_hr")
    hrv = _metric(snap.metrics, "hrv_sdnn") or _metric(snap.metrics, "hrv_rmssd")
    tips: list[str] = []
    if plan is not None and week.due >= 2 and week.done * 2 < week.due:
        head = f"这周计划 {week.due} 次只练了 {week.done} 次，不到一半："
        if plan.days_per_week > 2:
            fewer = max(2, min(plan.days_per_week - 1, week.done + 1))
            tips.append(head + f"可以把每周训练减到 {fewer} 天，更容易坚持。")
        else:  # 已经只有两练了：不再减天数，减每次的量
            tips.append(head + "每次少做一两个动作、缩短时间，先保证每周练到。")
    goal = snap.profile.goal
    if goal == "fat_loss" and weight is not None and weight.brief in ("基本持平", "在上升"):
        tips.append("减脂期体重这几周没有下降：建议每天少吃约 200 千卡，两周后再看体重趋势。")
    if sleep is not None and sleep.value is not None and sleep.value < 7:
        tips.append(
            f"最近 7 天平均只睡 {_fmt(sleep.value)} 小时：先把睡眠补到每晚 7 小时以上，比加练更有用。"
        )
    tired = [m.name for m in (rhr, hrv) if m is not None and m.tone == "attention"]
    if tired:
        tips.append(f"{'、'.join(tired)}比你平时差：这周适当减量，多休息。")
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
        "tips": tips[:MAX_TIPS],
    }
