"""出处标记（〔K03〕〔C2〕〔经验〕）只用于内部核对，用户看到的地方一律不带（项目负责人 10-30："回答不要带这种 K 什么了"）。"""

import json
from datetime import datetime

from ironm_agent.render import plan_card
from ironm_agent.training import Draft, Plan, WorkoutLog

MARKED = {"title": "入门全身〔K03〕", "goal": "健康", "days_per_week": 1, "sessions": [
    {"day": 1, "name": "全身 A", "minutes": 45, "items": [
        {"exercise": "高脚杯深蹲", "sets": 3, "reps": "8–12", "load": "还剩 2 次〔K28〕", "note": "膝盖对脚尖〔经验〕"}]}]}  # fmt: skip


def test_plans_and_logs_drop_marks_when_read() -> None:
    plan = Plan.model_validate(MARKED)
    text = json.dumps(plan.model_dump(), ensure_ascii=False)
    assert "〔" not in text and plan.sessions[0].items[0].load == "还剩 2 次"
    log = WorkoutLog.model_validate({"day": "2026-10-30", "session": "", "items": [
        {"exercise": "深蹲", "sets": 3, "reps": "5", "weight_kg": 60, "done_sets": []}],
        "done": True, "rpe": None, "minutes": None, "note": "下次加 2.5 公斤〔K03〕"})  # fmt: skip
    assert log.note == "下次加 2.5 公斤"


def test_plan_card_has_no_marks() -> None:
    draft = Draft("d1", "plan", {"plan": MARKED, "changes": "按新手方案排〔K03〕，周三练背〔经验〕"},
                  "pending", datetime.now().astimezone())  # fmt: skip
    blocks = plan_card(draft, Plan.model_validate(MARKED), None)
    shown = blocks[1]["content"]
    assert "〔" not in shown and "按新手方案排，周三练背" in shown




def test_memory_and_data_handles_are_dropped_too() -> None:
    from ironm_agent.checks import plain

    assert plain("首次用平时六到七成重量〔m20〕。") == "首次用平时六到七成重量。"
    assert plain("静息心率 58〔r3〕，比上周低〔C2〕。") == "静息心率 58，比上周低。"
