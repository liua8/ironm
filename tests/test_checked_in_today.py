"""打卡了就算今天的任务完成（spec [2026-10-23] §52）：档案写明今天已练完、训练教练不再安排今天、
说自己打过卡按训练问题、表达不满时不回打招呼。"""

from datetime import date

from ironm_agent.roles import Role
from ironm_agent.skills import core_of
from ironm_agent.training import Plan, WorkoutLog, case_lines, parse_plan

TUESDAY = date(2026, 10, 27)


def plan() -> Plan:
    p, why = parse_plan({
        "title": "三练全身加骑车", "goal": "增肌", "days_per_week": 4,
        "sessions": [
            {"day": 1, "name": "全身力量A", "minutes": 50, "items": [{"exercise": "箱式深蹲", "sets": 3, "reps": 10}]},
            {"day": 2, "name": "骑车有氧", "minutes": 30, "items": [{"exercise": "骑车", "sets": 1, "reps": "30 分钟"}]},
            {"day": 4, "name": "全身力量B", "minutes": 50, "items": [{"exercise": "哑铃卧推", "sets": 3, "reps": 10}]},
            {"day": 6, "name": "全身力量C", "minutes": 50, "items": [{"exercise": "单臂划船", "sets": 3, "reps": 10}]},
        ],
    })  # fmt: skip
    assert p is not None, why
    return p


MONDAY = WorkoutLog(day=date(2026, 10, 26), session="全身力量A", rpe=7)


def test_case_says_today_is_done() -> None:
    logs = [MONDAY, WorkoutLog(day=TUESDAY, session="骑车有氧", rpe=10, minutes=30)]
    lines = case_lines(plan(), logs, TUESDAY)
    done = [x for x in lines if "已打卡完成" in x]
    assert done == [
        "今天的骑车有氧已打卡完成（30 分钟、感受 10 分（到极限））：今天的训练任务已经完成，"
        "不要再安排今天怎么练、也不要把这次当成额外加练；"
        "问今天就只答今天已经练完，复盘这次、明天或下一次怎么练等他问到再说（这时做法和下一步都留空）"
    ]
    assert (
        lines.index(done[0])
        == next(i for i, x in enumerate(lines) if x.startswith("今天（周二）按计划")) + 1
    )
    assert any("本周已完成 2 次" in x and x.endswith("已含今天这一次") for x in lines)


def test_case_without_minutes_or_not_done() -> None:
    no_minutes = case_lines(plan(), [WorkoutLog(day=TUESDAY, session="骑车有氧", rpe=8)], TUESDAY)
    assert any(x.startswith("今天的骑车有氧已打卡完成（感受 8 分（吃力））：") for x in no_minutes)
    assert not any("分钟、" in x for x in no_minutes if "已打卡完成" in x)
    for logs in ([MONDAY], [MONDAY, WorkoutLog(day=TUESDAY, session="骑车有氧", done=False)]):
        lines = case_lines(plan(), logs, TUESDAY)
        assert not any("已打卡完成" in x or "已含今天" in x for x in lines)
    assert any(
        x.startswith("今天的训练已打卡完成")
        for x in case_lines(None, [WorkoutLog(day=TUESDAY)], TUESDAY)
    )


def test_trainer_rule_for_checked_in_day() -> None:
    core = core_of(Role.TRAINER)
    assert core is not None
    rule = "\n".join(core.rules)  # 训练的基础规程（§74；§87 起不再有训练教练的单独提示词）
    assert (
        "档案写了今天已打卡完成" in rule
        and "不再安排今天怎么练" in rule
        and "不把这次算成加练" in rule
        and "等他问到再说" in rule
    )


def test_rpe_has_its_meaning() -> None:
    from ironm_agent.training import rpe_word

    assert [rpe_word(x) for x in (1, 3, 4, 6, 7, 8, 9, 10)] == [
        "（很轻松）", "（很轻松）", "（中等）", "（中等）", "（吃力）", "（吃力）", "（到极限）", "（到极限）"
    ]  # fmt: skip
    assert "感受 10 分（到极限）" in WorkoutLog(day=TUESDAY, rpe=10).line()
