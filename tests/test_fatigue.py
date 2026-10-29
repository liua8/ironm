"""肌肉恢复度（spec [2026-10-23] §70 修改）：疲劳按指数消退，按肌肉类型、训练量、用力程度、习惯程度，
每个人按他说的校准。"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from ironm_agent.protools.fatigue import RATE_MAX, RATE_MIN, calibrate, recovery, tier
from ironm_agent.training import LogItem, WorkoutLog

DAY = date(2026, 10, 20)
AT = datetime.combine(DAY, time(18))
QUADS, CHEST, HAMS, CALF = (
    "muscle.quadriceps",
    "muscle.pec_major_lower",
    "muscle.hamstrings",
    "muscle.gastrocnemius",
)


def items(log: WorkoutLog, _: object) -> list[tuple[str, int]]:
    return [(x.exercise, x.sets or 1) for x in log.items]


def session(day: date, *moves: tuple[str, int], rpe: int | None = 7) -> WorkoutLog:
    return WorkoutLog(day=day, rpe=rpe, items=[LogItem(exercise=n, sets=s) for n, s in moves])


def accustomed(*moves: tuple[str, int]) -> list[WorkoutLog]:
    """两周前练过一次：不算"4 周没练过"。"""
    return [session(DAY - timedelta(days=14), *moves), session(DAY, *moves)]


def pct(logs: list[WorkoutLog], muscle: str, hours: float, **kw: object) -> int:
    return recovery(logs, AT + timedelta(hours=hours), None, items, [muscle], **kw)[muscle]  # type: ignore[arg-type]


def first_hour_at(logs: list[WorkoutLog], muscle: str, target: int = 90) -> int:
    return next(h for h in range(0, 200) if pct(logs, muscle, h) >= target)


def test_recovery_rises_and_upper_body_recovers_faster_than_legs() -> None:
    bench = accustomed(("杠铃卧推", 5))
    squat = accustomed(("杠铃深蹲", 5))
    assert pct(bench, CHEST, 0) < pct(bench, CHEST, 12) < pct(bench, CHEST, 36) <= 100
    assert 36 <= first_hour_at(bench, CHEST) <= 44  # 上肢约 40 小时到 90%
    assert 56 <= first_hour_at(squat, QUADS) <= 64  # 下肢约 60 小时
    assert pct(squat, CHEST, 0) == 100  # 没练到的不动


def test_hinge_slows_hamstrings_and_daily_muscles_recover_fast() -> None:
    rdl = accustomed(("罗马尼亚硬拉", 5))
    assert 68 <= first_hour_at(rdl, HAMS) <= 76  # 硬拉类腘绳肌约 72 小时
    calf = accustomed(("站姿提踵", 5))
    assert pct(calf, CALF, 0) < 50 and first_hour_at(calf, CALF) <= 30  # 日常用得多的约 28 小时


def test_more_sets_harder_effort_and_unaccustomed_recover_slower() -> None:
    base = accustomed(("杠铃深蹲", 4))
    assert pct(accustomed(("杠铃深蹲", 8)), QUADS, 24) < pct(base, QUADS, 24)
    hard = [
        session(DAY - timedelta(days=14), ("杠铃深蹲", 4)),
        session(DAY, ("杠铃深蹲", 4), rpe=9),
    ]
    assert pct(hard, QUADS, 24) < pct(base, QUADS, 24)
    fresh = [session(DAY, ("杠铃深蹲", 4))]  # 4 周内没练过
    assert pct(fresh, QUADS, 24) < pct(base, QUADS, 24)


def test_two_sessions_add_up() -> None:
    once = accustomed(("杠铃深蹲", 4))
    twice = [*once, session(DAY - timedelta(days=1), ("杠铃深蹲", 4))]
    assert pct(twice, QUADS, 12) < pct(once, QUADS, 12)


def test_assist_counts_half() -> None:
    bench = accustomed(("杠铃卧推", 4))  # 三角肌前束是辅助
    front = "muscle.anterior_delt"
    assert pct(bench, CHEST, 6) < pct(bench, front, 6) < 100


def test_tiers() -> None:
    assert [tier(x) for x in (0, 39, 40, 69, 70, 94, 95, 100)] == [
        "high", "high", "mid", "mid", "low", "low", "ready", "ready"
    ]  # fmt: skip


def test_personal_rate_slows_or_speeds_and_is_bounded() -> None:
    squat = accustomed(("杠铃深蹲", 5))
    assert (
        pct(squat, QUADS, 40, rates={QUADS: 1.5})
        < pct(squat, QUADS, 40)
        < pct(squat, QUADS, 40, rates={QUADS: 0.7})
    )
    assert calibrate(1.0, 95, "sore") == 1.1  # 算出已恢复他却说还酸：变慢
    assert calibrate(1.0, 40, "fine") == round(1 / 1.1, 3)  # 算出还累他说不酸了：变快
    assert calibrate(1.0, 70, "sore") is None and calibrate(1.0, 80, "fine") is None  # 对得上不调
    assert (
        calibrate(RATE_MAX, 99, "sore") == RATE_MAX and calibrate(RATE_MIN, 10, "fine") == RATE_MIN
    )
