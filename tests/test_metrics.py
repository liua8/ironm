"""指标计算：正常、数据不足、边界值。"""

from datetime import date, timedelta

import pytest

from ironm_agent import metrics as m

TODAY = date(2026, 10, 22)
END = date(2026, 9, 14)


def days(values: list[float], end: date = END) -> tuple[m.Point, ...]:
    return tuple((end - timedelta(days=len(values) - 1 - i), v) for i, v in enumerate(values))


def test_bmi_categories_follow_chinese_adult_standard() -> None:
    w = (END, 69.2)
    assert m.bmi(w, 175).value == 22.6 and m.bmi(w, 175).tone == "good"
    assert "18.5–23.9" in m.bmi(w, 175).source
    assert "超重" in m.bmi((END, 75.0), 175).text  # 24.5
    assert "肥胖" in m.bmi((END, 90.0), 175).text  # 29.4
    assert "过低" in m.bmi((END, 55.0), 175).text  # 18.0
    assert m.bmi((END, 73.4), 175).text.startswith("24")  # 23.97 → 24.0 归到超重一侧的写法要一致
    assert m.bmi(w, None).missing == ("身高（在个人中心填写）",) and m.bmi(w, None).value is None


def test_bmr_mifflin_and_missing_inputs() -> None:
    p = m.Profile(175, date(1992, 3, 1), "male", "muscle", "moderate")
    base = m.bmr((END, 69.2), p, TODAY)  # 10×69.2 + 6.25×175 − 5×34 + 5 = 1620.75
    assert base.value == 1621 and "6.25 × 175" in base.how
    female = m.bmr((END, 69.2), m.Profile(175, date(1992, 3, 1), "female"), TODAY)
    assert female.value == 1455  # 1620.75 − 166 = 1454.75
    gap = m.bmr((END, 69.2), m.Profile(), TODAY)
    assert gap.value is None and set(gap.missing) == {"身高", "出生日期", "性别"}


def test_tdee_and_targets_by_goal() -> None:
    p = m.Profile(175, date(1992, 3, 1), "male", "fat_loss", "moderate")
    base = m.bmr((END, 69.2), p, TODAY)
    total = m.tdee(base, p)
    assert total.value == round(1621 * 1.55)  # 2513
    cut = m.calorie_target(total, base, p)
    assert cut.value == 2013 and cut.ref == "K16"
    bulk = m.calorie_target(
        total, base, m.Profile(175, date(1992, 3, 1), "male", "muscle", "moderate")
    )
    assert bulk.value == round(2513 * 1.1)
    assert m.calorie_target(
        total, base, m.Profile(175, date(1992, 3, 1), "male", None, "moderate")
    ).missing


def test_fat_loss_target_never_below_bmr_or_floor() -> None:
    p = m.Profile(160, date(1990, 1, 1), "female", "fat_loss", "sedentary")
    base = m.bmr((END, 50.0), p, TODAY)  # 500 + 1000 − 180 − 161 = 1159
    target = m.calorie_target(m.tdee(base, p), base, p)
    assert target.value == 1200 and "安全下限" in target.how


def test_protein_range_by_goal() -> None:
    assert m.protein_target((END, 70.0), m.Profile(goal="muscle")).text.startswith(
        "每天 112–140 克"
    )
    assert m.protein_target((END, 70.0), m.Profile()).text.startswith("每天 98–112 克")
    assert m.protein_target(None, m.Profile()).missing == ("体重记录",)


def test_weight_trend_slope_and_confidence() -> None:
    falling = days([70 - 0.03 * i for i in range(28)])  # 每天 −0.03 → 每周 −0.21
    t = m.weight_trend(falling)
    assert t.value == -0.21 and "在下降" in t.text
    flat = days([70, 70.4, 69.8, 70.2, 69.9, 70.1, 70.0, 70.3, 69.7, 70.1] + [70.0] * 6)  # 跨 15 天
    assert "不明显" in m.weight_trend(flat).text


def test_weight_trend_needs_enough_points_and_span() -> None:
    few = days([70, 69.9, 69.8])
    assert m.weight_trend(few).value is None and "至少 6 次" in m.weight_trend(few).missing[0]


def test_weekly_weighing_widens_the_window() -> None:
    # 一周称一次：4 周只有 4 次，放宽到 8 周（8 次）
    weekly = tuple((END - timedelta(days=7 * i), 70.0 - 0.1 * (7 - i)) for i in range(8))
    t = m.weight_trend(weekly)
    assert t.value is not None and "最近 8 周" in t.text


def test_resting_hr_against_own_baseline() -> None:
    steady = days([58.0] * 50 + [57, 59] * 5)
    assert "正常波动范围内" in m.resting_hr(steady).text
    rising = days([56, 57, 58, 57, 56, 58, 57] * 7 + [66] * 7)
    r = m.resting_hr(rising)
    assert r.tone == "attention" and "明显高于" in r.text


def test_baseline_too_short_gives_average_without_judgement() -> None:
    r = m.resting_hr(days([58.0] * 10))
    assert r.value == 58.0 and "暂不比较" in r.text and r.tone == "neutral"


def test_hrv_algorithms_stay_separate() -> None:
    out = m.compute_all(
        m.Readings(hrv_sdnn=days([45.0] * 30), hrv_rmssd=days([38.0] * 30)), m.Profile(), TODAY
    )
    names = [x.name for x in out]
    assert "心率变异性（SDNN）" in names and "心率变异性（RMSSD）" in names


def test_steps_reference_depends_on_age() -> None:
    assert "8000–10000" in m.steps(days([9000.0] * 7), 34).text
    assert "6000–8000" in m.steps(days([7000.0] * 7), 65).text


def test_sleep_and_blood_pressure() -> None:
    s = m.sleep(days([6.5, 7.2, 6.8, 7.5, 6.0, 7.0, 6.9]))
    assert s.value == 6.8 and "4 天不足 7 小时" in s.text and s.tone == "attention"
    bp = m.blood_pressure((END, 128.0), (END, 82.0))
    assert "正常高值" in bp.text and "不作诊断" in bp.text
    assert "≥ 140/90" in m.blood_pressure((END, 142.0), (END, 85.0)).text


@pytest.mark.parametrize(
    "key", ["weight", "bmi", "bmr", "tdee", "kcal_target", "protein_target", "sleep", "steps"]
)
def test_nothing_recorded_means_no_numbers(key: str) -> None:
    out = {x.key: x for x in m.compute_all(m.Readings(), m.Profile(), TODAY)}
    assert out[key].value is None and out[key].missing


def test_profile_height_falls_back_to_recorded_height() -> None:
    out = {
        x.key: x
        for x in m.compute_all(m.Readings(weight=days([69.2]), height_cm=175), m.Profile(), TODAY)
    }
    assert out["bmi"].value == 22.6


def test_cards_get_a_short_conclusion_and_display_value() -> None:
    """卡片上只放一个数和一个短结论；长说明留给详情。"""
    assert m.bmi((END, 69.2), 175).brief == "正常" and m.bmi((END, 90.0), 175).brief == "肥胖"
    bp = m.blood_pressure((END, 112), (END, 71))
    assert (bp.brief, bp.display) == ("正常", "112/71")
    assert m.blood_pressure((END, 145), (END, 85)).brief == "偏高"
    flat = days([69.2, 69.4, 69.1, 69.3, 69.2, 69.0, 69.3] * 3)
    assert m.weight_trend(flat).brief == "基本持平"
    falling = days([71 - 0.07 * i for i in range(28)])
    assert m.weight_trend(falling).brief == "在下降"
    protein = m.protein_target((END, 69.2), m.Profile(goal="fat_loss"))
    assert (protein.display, protein.brief) == ("111–138", "减脂")
    assert (
        m.steps(days([9000] * 7), 31).brief == "达标" and m.sleep(days([6.0] * 7)).brief == "偏少"
    )
    calm = m.resting_hr(days([56.0, 57.0] * 35))
    assert calm.brief == "正常波动"
    tired = m.resting_hr(days([56.0, 57.0] * 30 + [63.0] * 7))
    assert (tired.brief, tired.tone) == ("明显偏高", "attention")
    assert m.resting_hr(days([56.0] * 10)).brief == "基线积累中"
