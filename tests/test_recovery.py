"""每块肌肉的恢复（spec [2026-10-23] §30）：底数按肌肉、加天数、封顶、本人说的优先。不连数据库。"""

from datetime import date, timedelta

from ironm_agent.protools.muscle_map import _done_items
from ironm_agent.protools.recovery import recovery
from ironm_agent.training import LogItem, WorkoutLog

TODAY = date(2026, 10, 25)


def log(back: int, *items: tuple[str, int], rpe: int | None = None) -> WorkoutLog:
    return WorkoutLog(day=TODAY - timedelta(days=back), rpe=rpe,
                      items=[LogItem(exercise=e, sets=n) for e, n in items])  # fmt: skip


def rec(logs: list[WorkoutLog], feels: dict | None = None) -> dict:  # type: ignore[type-arg]
    return {m: r.json(TODAY) for m, r in recovery(logs, TODAY, None, _done_items, feels).items()}


def test_lower_body_two_days_upper_body_one_day() -> None:
    habit = [log(10, ("杠铃深蹲", 3), ("哑铃卧推", 3))]  # 4 周内练过：不算"不习惯"
    r = rec([log(1, ("杠铃深蹲", 3), ("哑铃卧推", 3)), *habit])
    assert r["股四头肌"]["ready_on"] == "2026-10-26" and r["股四头肌"]["recover_days"] == 2
    assert "下肢多关节" in r["股四头肌"]["recover_why"][0]
    assert (
        r["胸大肌"]["state"] == "ready" and r["胸大肌"]["recover_days"] == 1
    )  # 昨天练的，今天可以练
    assert r["三角肌前束"]["recover_days"] == 0  # 只是辅助练到：不算恢复
    today = rec([log(0, ("哑铃卧推", 3)), log(10, ("哑铃卧推", 3))])
    assert today["胸大肌"]["state"] == "today" and today["胸大肌"]["ready_on"] == "2026-10-26"


def test_adds_days_for_failure_volume_lengthened_and_unaccustomed() -> None:
    habit = [log(10, ("罗马尼亚硬拉", 3), ("杠铃深蹲", 3))]
    rdl = rec([log(0, ("罗马尼亚硬拉", 3)), *habit])["腘绳肌"]
    assert rdl["recover_days"] == 3 and "拉长位置" in rdl["recover_why"][0]
    hard = rec([log(0, ("杠铃深蹲", 8), rpe=9), *habit])["股四头肌"]
    assert hard["recover_days"] == 4 and any("接近力竭" in w for w in hard["recover_why"])
    assert any("8 组" in w for w in hard["recover_why"])
    new_arm = rec([log(0, ("哑铃弯举", 3))])["肱二头肌"]  # 4 周内没练过：手臂多加两天
    assert new_arm["recover_days"] == 3 and any("不习惯" in w for w in new_arm["recover_why"])
    capped = rec([log(0, ("罗马尼亚硬拉", 9), rpe=10)])["腘绳肌"]
    assert capped["recover_days"] == 4 and any("最多按 4 天" in w for w in capped["recover_why"])


def test_own_feel_comes_first() -> None:
    logs = [log(0, ("杠铃深蹲", 3)), log(10, ("杠铃深蹲", 3))]
    assert rec(logs, {"股四头肌": ("fine", TODAY)})["股四头肌"]["state"] == "ready"
    sore = rec(logs, {"腘绳肌": ("sore", TODAY - timedelta(days=8))})["腘绳肌"]
    assert sore["state"] == "sore" and sore["sore_too_long"]
    assert rec(logs, {"腘绳肌": ("sore", TODAY - timedelta(days=20))})["腘绳肌"]["state"] == "ready"
    # 说酸之后又练了：按新的这次算，不再按以前说的
    later = rec(
        [log(0, ("杠铃深蹲", 3)), log(10, ("杠铃深蹲", 3))],
        {"股四头肌": ("sore", TODAY - timedelta(days=3))},
    )
    assert later["股四头肌"]["state"] == "today"
