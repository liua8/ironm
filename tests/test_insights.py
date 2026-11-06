"""读懂指标趋势（spec [2026-10-23] §84）：和自己比也和标准比、同期发生的事、依据可追问；只给事实不贴标签（§182）。"""

import asyncio
from datetime import date, timedelta
from typing import Any

from ironm_agent.casefile import Snapshot
from ironm_agent.insights import compare, observations
from ironm_agent.metrics import Profile, Readings, compute_all
from ironm_agent.protools.registry import ToolContext, run
from ironm_agent.training import LogItem, SetDone, WorkoutLog
from tests.test_coach import TODAY

ME = Profile(
    height_cm=178, birth=date(1994, 5, 1), sex="male", goal="fat_loss", activity="moderate"
)


def wiggle(i: int) -> int:
    return i * 7 % 5 - 2  # 平常的日常波动


def days(n: int, f: Any) -> tuple[tuple[date, float], ...]:
    return tuple((TODAY - timedelta(days=i), float(f(i))) for i in range(n))


def tired() -> Readings:
    """这周静息心率比平常高、心率变异性比平常低、睡得少；步数掉了；体重在掉。"""
    return Readings(
        resting_hr=days(40, lambda i: 66 + wiggle(i) * 0.3 if i < 7 else 58 + wiggle(i)),
        hrv_sdnn=days(40, lambda i: 38 if i < 7 else 52 + wiggle(i) * 2),
        sleep_hours=days(30, lambda i: 6.0 if i < 7 else 7.4),
        steps=days(30, lambda i: 5000 if i < 7 else 9000),
        weight=days(28, lambda i: 80 + 0.13 * i),
        systolic=days(10, lambda i: 128),
        diastolic=days(10, lambda i: 82),
    )


def workouts(*back: int) -> list[WorkoutLog]:
    sets = [SetDone(reps=8, weight_kg=60)] * 3
    return [WorkoutLog(day=TODAY - timedelta(days=b), session="下肢",
                       items=[LogItem(exercise="杠铃深蹲", done_sets=sets)]) for b in back]  # fmt: skip


BUSY = workouts(0, 1, 2, 3, 5, 9, 13, 16, 20, 23, 27)  # 这周 5 次，前三周每周 2 次


def test_each_reading_is_compared_with_himself_and_a_standard() -> None:
    got = {r.key: r for r in compare(tired(), ME, TODAY)}
    assert "60–100" in got["resting_hr"].standard and "K20" in got["resting_hr"].refs
    assert "没有公认的人群标准" in got["hrv_sdnn"].standard  # 只和自己比，说明为什么
    assert "低于成年人每晚 7 小时" in got["sleep"].standard and "前三周平均" in got["sleep"].mine
    assert "低于成年人每天 8000 步" in got["steps"].standard
    assert "正常高值" in got["blood_pressure"].standard
    assert (
        "减脂每周减体重的 0.5–1%" in got["weight"].standard and "偏快" not in got["weight"].standard
    )
    older = Profile(
        height_cm=170, birth=date(1956, 1, 1), sex="female", goal="health", activity="light"
    )
    assert "每天 6000 步" in {r.key: r for r in compare(tired(), older, TODAY)}["steps"].standard


LABELS = ("恢复不够", "睡得少", "活动量掉了", "减得太快", "增重太快", "偏快", "好", "一般", "差")


def test_observations_are_numbers_against_his_own_past_not_labels() -> None:
    """§182 需求 7：只给数、和他自己之前比的差、时间段；不贴"恢复不够、睡得少"这类标签。"""
    found = {o.kind: o for o in observations(tired(), ME, TODAY, logs=BUSY, illness=["昨天说感冒"],
                                             events=["去上海开会"])}  # fmt: skip
    assert (
        "最近 7 天平均 66 次/分" in found["resting_hr"].seen
        and "高 8 次/分" in found["resting_hr"].seen
    )
    assert "最近 7 天平均 38 毫秒" in found["hrv_sdnn"].seen and "低 27%" in found["hrv_sdnn"].seen
    assert "前三周平均 7.4 小时，低 1.4 小时" in found["sleep"].seen
    assert "前三周平均 9000 步，低 44%" in found["steps"].seen
    assert "减脂每周减体重的 0.5–1% 比较合理" in found["weight"].seen
    assert found["training"].seen == "最近 7 天练了 5 次，前三周平均每周 2 次"
    assert found["illness"].seen == "昨天说感冒" and found["event"].seen == "去上海开会"
    assert found["resting_hr"].refs == ("K18",)
    for o in found.values():
        assert not any(w in o.line() for w in LABELS), o.line()
        assert "怎么调" not in o.line()  # 只是事实，调不调由模型决定（§85）
    assert [o.kind for o in observations(Readings(), ME, TODAY)] == ["thin"]


def snapshot_of(r: Readings) -> Snapshot:
    return Snapshot(ME, r, tuple(compute_all(r, ME, TODAY)), TODAY)


def test_case_file_and_tools_carry_sources_for_follow_up_questions() -> None:
    from ironm_agent.casefile import build as build_case
    from ironm_agent.memory_view import Recall

    found = observations(tired(), ME, TODAY, logs=BUSY)
    case = build_case(snapshot_of(tired()), Recall(()), "我最近怎么样",
                      insights=[(s.line(), s.detail()) for s in found])  # fmt: skip
    text = case.text()
    assert (
        "指标解读" in text and "静息心率：最近 7 天平均 66 次/分" in text and "不说成因果" in text
    )
    assert "恢复不够" not in text and "睡得少" not in text
    cid = case.insights[0][0]
    assert "依据：K18" in case.calcs[cid] and "数据：" in case.calcs[cid]
    ctx = ToolContext(TODAY, goal="fat_loss", readings=tired(), profile=ME, found=tuple(found))
    got = asyncio.run(run("explain_trends", ctx, {}))
    names = [f.name for f in got.findings]
    assert "静息心率（两种比较）" in names and "同期：训练次数" in names
    assert not any("认出的情况" in n for n in names)
    rhr = next(f for f in got.findings if f.name == "静息心率（两种比较）")
    assert "静息心率的正常范围" in rhr.source  # 追问依据时讲得出资料名称
    trend = asyncio.run(run("trend_analysis", ctx, {"indicator": "resting_hr", "days": 28}))
    assert any(n.startswith("和标准比：在成年人正常范围") for n in trend.notes)
