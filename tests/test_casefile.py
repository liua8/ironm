"""共享档案（spec [2026-10-23] §2、§5）：今天的身体数据（只给数、不定级，§182）、风险提示、伤病部位、档案的写法与编号。"""

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


LEVELS = ("好", "一般", "差", "恢复不够", "睡得少", "数据不足")


def test_body_data_is_numbers_against_his_own_baseline_not_a_level() -> None:
    """§182 需求 7：睡了几小时、静息心率比平时高几、心率变异性比平时低百分之几；不写好、一般、差。"""
    r = Readings(
        sleep_hours=steady(7.3, last=[4.8, 5.2, 4.5]),
        resting_hr=steady(58, last=[64, 66, 67]),
        hrv_sdnn=steady(55, last=[40, 37, 35]),
    )
    state = readiness(r, "今天练什么", TODAY)
    assert state.facts[0] == (
        "睡眠：最近一晚（今天）4.5 小时，最近 3 晚平均 4.8 小时，你平时 7.3 小时，少 2.8 小时"
    )
    assert state.facts[1] == "静息心率：最近 3 天平均 66 次/分，你平时 58 次/分，高 8 次/分"
    assert state.facts[2] == "心率变异性（SDNN）：最近 3 天平均 37 毫秒，你平时 55 毫秒，低 32%"
    line = state.line()
    assert line.startswith("今天的身体数据：") and not any(w in line for w in LEVELS), line
    assert not state.sick and state.current


def test_dates_when_not_today_and_no_recent_data_says_so() -> None:
    yesterday = Readings(resting_hr=tuple((d - timedelta(days=1), v) for d, v in steady(58)))
    assert readiness(yesterday, "", TODAY).facts == (
        "静息心率：最近 3 天平均 58 次/分（最近一次 10 月 22 日），你平时 58 次/分，和平时一样",
    )
    assert readiness(Readings(resting_hr=series([60.0, 61.0])), "", TODAY).facts == (
        "静息心率：最近 3 天平均 60 次/分，你平时的记录还不到 14 天，暂不比较",
    )
    old = Readings(sleep_hours=tuple((d - timedelta(days=30), v) for d, v in steady(7.3)))
    state = readiness(old, "今天练什么", TODAY)
    assert (
        state.facts == ("最近 3 天没有睡眠、心率记录（最近一次是 9 月 23 日）",)
        and not state.current
    )


def test_only_saying_sick_is_read_from_the_sentence() -> None:
    """这句话本人说生病了：回答核对的安全护栏照旧用（§182）；累、睡了几小时不再由关键词定级，管家读原话。"""
    sick = readiness(Readings(), "感冒了还能去健身吗", TODAY)
    assert sick.sick and sick.facts == ("还没有睡眠、心率记录",)
    tired = readiness(Readings(), "昨晚只睡了 4 个小时，今天很累", TODAY)
    assert not tired.sick and tired.facts == ("还没有睡眠、心率记录",)
    ill = readiness(Readings(), "", TODAY, illness="昨天说感冒")
    assert ill.facts[-1] == "生病：昨天说感冒" and not ill.sick  # 生病经过是事实；练不练由管家定


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
        "今天的身体数据：睡眠：最近一晚（今天）"
    )
    assert "今天的身体状态" not in text and "代码只算数、不下结论" in text
    assert "指标计算" not in case.text(calcs=False)
    assert case.injuries == ("joint.knee",)


def test_case_file_without_any_data() -> None:
    case = build(Snapshot(), Recall(), "帮我做个训练计划")
    assert case.basics == "目标未填写" and case.readiness.facts == ("还没有睡眠、心率记录",)
    assert case.risks == ()


def test_pain_must_be_the_users_own_and_not_negated() -> None:
    """独立审查：句子里有"疼/响"就把提到的部位都算伤（"影响"里有"响"），否定和旁人也不分。"""
    assert injured_parts([], "深蹲会影响膝盖吗") == ()
    assert injured_parts([], "膝盖不疼，深蹲怎么加重") == ()
    assert injured_parts([], "我妈膝盖疼") == ()
    assert injured_parts([], "我妈膝盖疼，我自己膝盖也疼") == ("joint.knee",)
    assert injured_parts([], "疼在膝盖外侧") == ("joint.knee",)


def test_sickness_must_be_the_users_own() -> None:
    assert readiness(Readings(), "感冒了还能去健身吗", TODAY).sick
    assert not readiness(Readings(), "我没有感冒，今天练什么", TODAY).sick
    assert not readiness(Readings(), "感冒好了能练吗", TODAY).sick
    assert not readiness(Readings(), "我妈感冒了，我今天练什么", TODAY).sick


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
    assert case.readiness.facts == ("这次没读到你的健康数据",) and "没读到" in case.basics
