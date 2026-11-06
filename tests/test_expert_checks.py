"""专家视角核对补漏（spec [2026-10-23] §47）。"""

from ironm_agent.checks import check_text, repair
from ironm_agent.constraints import Context, annotate, check

SICK = Context(sick=True)


def test_discouraging_wording_counts_as_a_limit() -> None:
    for text in (
        "这种状态下冲大重量只会加重疲劳、动作也容易变形。",
        "这种状态下做大重量和练到力竭只会加深疲劳。",
    ):
        assert check(text, SICK) == [], text
        assert annotate(text, SICK) == text
    assert "（生病时先别做）" in annotate("今天可以冲大重量。", SICK)


def _check(text: str) -> list[str]:
    return check_text(
        text,
        support={},
        entries={},
        question="体重有变化吗",
        calcs={"C1": "最近 4 周每周 -0.14 公斤，可信范围 -0.25 至 -0.03"},
    )


def test_false_zero_crossing_is_caught_and_dropped() -> None:
    bad = "最近 4 周每周 -0.14 公斤，可信范围 -0.25 至 -0.03，虽然跨过零但偏向下〔C1〕。体重在慢慢下降。"
    assert any("跨过零" in p for p in _check(bad))
    fixed = repair(
        bad,
        support={},
        entries={},
        question="体重有变化吗",
        calcs={"C1": "最近 4 周每周 -0.14 公斤，可信范围 -0.25 至 -0.03"},
    )
    assert "跨过零" not in fixed and "-0.25 至 -0.03" in fixed and "体重在慢慢下降" in fixed
    assert _check(fixed) == []
    ok = "可信范围 -0.25 至 0.10，跨过零，变化不明显〔经验〕。"
    assert not any("跨过零" in p for p in _check(ok))


def test_macros_must_fit_the_calories() -> None:
    kinds = lambda t: [v.kind for v in check(t, Context())]  # noqa: E731
    bad = "每天吃 1800 千卡，蛋白质 150 克，碳水 400 克。"
    assert kinds(bad) == ["macros"]
    assert "（和每天热量对不上，以热量目标为准）" in annotate(bad, Context())
    fits = "每天 2500–2600 千卡，蛋白质每天 130–150 克，碳水每天约 375–525 克。"
    assert kinds(fits) == []
    assert kinds("每天 1800 千卡。") == [] and kinds("蛋白质 150 克，碳水 400 克。") == []
