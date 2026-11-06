"""旧数据不能当成现在的（spec [2026-10-23] §102）：最近 7 天从今天往前数，没有新记录就不下结论。"""

from __future__ import annotations

from datetime import date, timedelta

from ironm_agent import metrics as m
from ironm_agent.agent import _PROMPT
from ironm_agent.insights import compare, observations

TODAY = date(2026, 11, 2)
OLD_END = date(2026, 9, 14)  # 心率、步数最后一条：7 周前


def series(end: date, values: list[float]) -> tuple[m.Point, ...]:
    return tuple((end - timedelta(days=len(values) - 1 - i), v) for i, v in enumerate(values))


# 心率、步数停在 7 周前，睡眠只有两晚，体重今天还在称
OLD_RHR = series(OLD_END, [56.0, 57.0] * 30 + [63.0] * 7)  # 最后一周比基线高
OLD_STEPS = series(OLD_END, [8400.0] * 30)
SLEEP = ((date(2026, 10, 20), 7.6), (date(2026, 10, 27), 7.4))
WEIGHT = series(TODAY, [70.0])


def test_no_record_in_the_last_week_means_no_number_and_no_verdict() -> None:
    for got, name in ((m.resting_hr(OLD_RHR, TODAY), "静息心率"), (m.steps(OLD_STEPS, 34, TODAY), "步数"),
                      (m.hrv(series(OLD_END, [50.0] * 20), "SDNN", TODAY), "心率变异性")):  # fmt: skip
        assert got.value is None and not got.ok and got.brief == "没有新数据", name
        assert f"最近 7 天没有{name}" in got.text and "最近一次是 9月14日" in got.text
        assert got.series  # 历史趋势图照旧画


def test_few_records_say_how_many() -> None:
    s = m.sleep(SLEEP, TODAY)
    assert s.value == 7.4 and s.text.startswith("最近 7 天有 1 晚记录，平均 7.4 小时")
    assert (
        "最近 7 天没有睡眠时长记录（最近一次是 10月27日）"
        in m.sleep(SLEEP, TODAY + timedelta(days=7)).text
    )
    assert m.week_text(7, "7", "小时", nights=True) == "最近 7 天平均 7 小时"


def test_weight_and_blood_pressure_carry_dates() -> None:
    now = m.weight_now(WEIGHT, TODAY)
    assert now.value == 70.0 and "最近一次 70 公斤（11月2日）" in now.text
    old = m.weight_now(series(OLD_END, [69.0] * 10), TODAY)
    assert old.value == 69.0 and "（9月14日）" in old.text and "最近 7 天没有称重" in old.text
    assert not m.weight_trend(
        series(OLD_END, [70.0 - 0.05 * i for i in range(40)]),
        TODAY - timedelta(days=0) + timedelta(days=90),
    ).ok
    assert "（9月14日）" in m.blood_pressure((OLD_END, 128.0), (OLD_END, 82.0)).text


def test_case_metrics_and_insights_no_longer_use_old_numbers() -> None:
    r = m.Readings(weight=WEIGHT, resting_hr=OLD_RHR, steps=OLD_STEPS, sleep_hours=SLEEP)
    p = m.Profile(
        height_cm=175, birth=date(1992, 3, 1), sex="male", goal="muscle", activity="moderate"
    )
    text = "\n".join(x.text for x in m.compute_all(r, p, TODAY))
    assert "最近 7 天平均 59" not in text and "最近 7 天平均 8400" not in text
    assert "最近 7 天没有静息心率记录" in text and "最近 7 天有 1 晚记录" in text
    readings = {x.key for x in compare(r, p, TODAY)}
    assert "resting_hr" not in readings and "steps" not in readings  # 旧的不拿来和标准比
    sick = ("昨天说感冒",)
    found = {x.kind for x in observations(r, p, TODAY, illness=sick)}
    assert "resting_hr" not in found and "steps" not in found  # 7 周前的心率、步数不当成最近的变化
    then = date(2026, 9, 14)  # 当时看：最后一周有记录，照常给最近和之前的差
    assert "resting_hr" in {x.kind for x in observations(r, p, then, illness=sick)}


def test_the_answer_prompt_says_old_data_needs_a_date() -> None:
    assert "数据不是最近 7 天的，说清是哪天的，不当成现在的状态" in _PROMPT
