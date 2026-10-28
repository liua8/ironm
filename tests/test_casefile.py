"""共享档案（spec [2026-10-23] §2、§5）：今天的身体状态、风险提示、伤病部位、档案的写法与编号。"""

from datetime import UTC, date, datetime, timedelta

from ironm_agent.casefile import Snapshot, build, injured_parts, readiness, risks
from ironm_agent.memory_store import Item
from ironm_agent.memory_view import Recall
from ironm_agent.metrics import Profile, Readings, compute_all

TODAY = date(2026, 10, 23)
T0 = datetime(2026, 10, 20, tzinfo=UTC)


def series(values: list[float], start_ago: int | None = None) -> tuple[tuple[date, float], ...]:
    """从早到晚的每天一个值，最后一个是今天。"""
    n = len(values)
    return tuple((TODAY - timedelta(days=n - 1 - i), v) for i, v in enumerate(values))


def steady(
    base: float, days: int = 40, last: list[float] | None = None
) -> tuple[tuple[date, float], ...]:
    values = [base + (0.5 if i % 2 else -0.5) for i in range(days)]
    if last:
        values[-len(last) :] = last
    return series(values)


def item(category: str, content: str, *, status: str = "active", created: datetime = T0) -> Item:
    return Item(content[:6], category, content, content, "said", status, created, created)  # type: ignore[arg-type]


def test_poor_when_short_sleep_and_heart_signals_are_off() -> None:
    r = Readings(
        sleep_hours=steady(7.3, last=[4.8, 5.2, 4.5]),
        resting_hr=steady(58, last=[64, 66, 67]),
        hrv_sdnn=steady(55, last=[40, 37, 35]),
    )
    state = readiness(r, "今天练什么", TODAY)
    assert state.level == "poor" and state.name == "差"
    assert any("4.5 小时" in x for x in state.reasons)
    assert any("静息心率" in x for x in state.reasons) and any("SDNN" in x for x in state.reasons)


def test_good_when_recent_data_is_normal_and_unknown_without_recent_data() -> None:
    r = Readings(sleep_hours=steady(7.3), resting_hr=steady(58), hrv_sdnn=steady(55))
    assert readiness(r, "今天练什么", TODAY).level == "good"
    old = Readings(sleep_hours=tuple((d - timedelta(days=30), v) for d, v in steady(7.3)))
    state = readiness(old, "今天练什么", TODAY)
    assert state.level == "unknown" and state.name == "数据不足"


def test_what_the_user_says_counts() -> None:
    assert readiness(Readings(), "昨晚只睡了 4 个小时，今天还能练腿吗", TODAY).level == "poor"
    assert readiness(Readings(), "睡了五个多小时", TODAY).level == "fair"
    sick = readiness(Readings(), "感冒了还能去健身吗", TODAY)
    assert sick.level == "poor" and sick.sick
    # 一般的两条加在一起算差
    assert readiness(Readings(), "没睡好，今天很累", TODAY).level == "poor"


def test_blood_pressure_risks_use_the_latest_reading_in_the_window() -> None:
    crisis = Readings(
        systolic=((TODAY - timedelta(days=2), 186.0),),
        diastolic=((TODAY - timedelta(days=2), 114.0),),
    )
    found = risks(crisis, (), TODAY)
    assert [x.key for x in found] == ["bp_crisis"] and found[0].block
    assert "186/114" in found[0].note and "120" in found[0].note
    high = Readings(
        systolic=((TODAY - timedelta(days=3), 164.0),),
        diastolic=((TODAY - timedelta(days=3), 102.0),),
    )
    assert [(x.key, x.block) for x in risks(high, (), TODAY)] == [("bp_high", False)]
    old = Readings(
        systolic=((TODAY - timedelta(days=40), 190.0),),
        diastolic=((TODAY - timedelta(days=40), 120.0),),
    )
    assert risks(old, (), TODAY) == ()  # 太久以前的读数不算


def test_memory_risks_only_from_active_conditions() -> None:
    memory = [
        item("injury", "怀孕 24 周"),
        item("injury", "去年做过心脏支架"),
        item("injury", "以前有高血压", status="resolved"),
        item("injury", "半年前做过膝盖手术", created=datetime(2026, 4, 1, tzinfo=UTC)),
        item("diet", "糖尿病饮食"),  # 不是伤病与身体状况这一类
    ]
    assert [x.key for x in risks(Readings(), memory, TODAY)] == ["pregnancy", "cardiac"]


def test_injured_parts_from_memory_and_current_pain() -> None:
    memory = [item("injury", "左膝旧伤，蹲深了会疼"), item("injury", "腰扭过", status="resolved")]
    assert injured_parts(memory, "今天练什么") == ("joint.knee",)
    assert injured_parts(memory, "卧推的时候肩膀前面疼怎么办") == ("joint.knee", "joint.shoulder")
    assert injured_parts([], "肩膀训练怎么安排") == ()  # 没说疼就不算


def test_case_file_numbers_have_ids_and_match_the_metrics_tool() -> None:
    profile = Profile(
        height_cm=175, birth=date(1996, 3, 15), sex="male", goal="muscle", activity="moderate"
    )
    readings = Readings(weight=steady(75, days=30), sleep_hours=steady(7.3), resting_hr=steady(58))
    metrics = tuple(compute_all(readings, profile, TODAY))
    recall = Recall.of(
        [item("injury", "左膝旧伤，蹲深了会疼"), item("equipment", "一对 20 公斤哑铃")],
        datetime(2026, 10, 23, tzinfo=UTC),
    )
    case = build(Snapshot(profile, readings, metrics, TODAY), recall, "今天练什么")
    text = case.text()
    assert "男，30 岁，身高 175 厘米" in case.basics and "目标增肌" in case.basics
    assert "左膝旧伤" in text and "20 公斤哑铃" in text
    assert case.calcs["C0"].startswith("档案：")
    bmi = next(i for i, m in enumerate(metrics, start=1) if m.key == "bmi")
    assert f"[C{bmi}] BMI" in text and f"C{bmi}" in case.calcs  # 与 compute_metrics 同样的编号
    assert case.readiness_id == f"C{len(metrics) + 1}" and case.calcs[case.readiness_id].startswith(
        "今天的身体状态"
    )
    assert "指标计算" not in case.text(calcs=False)
    assert case.injuries == ("joint.knee",)


def test_case_file_without_any_data() -> None:
    case = build(Snapshot(), Recall(), "帮我做个训练计划")
    assert case.basics == "目标未填写" and case.readiness.level == "unknown" and case.risks == ()


def test_pain_must_be_the_users_own_and_not_negated() -> None:
    """独立审查：句子里有"疼/响"就把提到的部位都算伤（"影响"里有"响"），否定和旁人也不分。"""
    assert injured_parts([], "深蹲会影响膝盖吗") == ()
    assert injured_parts([], "膝盖不疼，深蹲怎么加重") == ()
    assert injured_parts([], "我妈膝盖疼") == ()
    assert injured_parts([], "我妈膝盖疼，我自己膝盖也疼") == ("joint.knee",)
    assert injured_parts([], "疼在膝盖外侧") == ("joint.knee",)


def test_sickness_and_sleep_must_be_the_users_own() -> None:
    assert readiness(Readings(), "我没有感冒，今天练什么", TODAY).level == "unknown"
    assert readiness(Readings(), "感冒好了能练吗", TODAY).level == "unknown"
    assert readiness(Readings(), "我妈感冒了，我今天练什么", TODAY).level == "unknown"
    assert readiness(Readings(), "我妈只睡了 4 小时", TODAY).level == "unknown"
    assert readiness(Readings(), "我不累", TODAY).level == "unknown"


def test_any_high_reading_in_the_window_counts() -> None:
    """独立审查：只看最新一次，三天前 190/115、今天 158/98 时既不提醒也不约束。"""
    r = Readings(
        systolic=((TODAY - timedelta(days=3), 190.0), (TODAY, 158.0)),
        diastolic=((TODAY - timedelta(days=3), 115.0), (TODAY, 98.0)),
    )
    [found] = risks(r, (), TODAY)
    assert found.key == "bp_crisis" and "190/115" in found.note


def test_failed_read_is_said_plainly() -> None:
    case = build(Snapshot(failed=True), Recall(), "今天练什么")
    assert case.readiness.reasons == ("这次没读到你的健康数据",) and "没读到" in case.basics
