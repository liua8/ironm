"""读数据：同一类数据可能来自好几个来源（种子数据、苹果健康导入），按日期合并，同一天取最新的来源。"""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from ironm_agent.healthdata import candidates, merge, read_all

TODAY = date(2026, 10, 23)


@dataclass
class Env:
    status: str = "ok"
    data: list[dict[str, Any]] | None = None


def days(first: date, values: list[float], unit: str = "") -> list[dict[str, Any]]:
    return [
        {"period": (first + timedelta(days=i)).isoformat(), "avg": v, "unit": unit}
        for i, v in enumerate(values)
    ]


class FakeHealth:
    """假的 mirobody 指标查询：不给名字时返回目录；给名字时按天返回。"""

    def __init__(
        self, series: Mapping[str, list[dict[str, Any]]], catalog_fails: bool = False
    ) -> None:
        self.series = series
        self.catalog_fails = catalog_fails

    async def envelope(
        self, who: Mapping[str, str], indicators: list[str] | None = None, **_: Any
    ) -> Env:
        if not indicators:
            if self.catalog_fails:
                raise ConnectionError("down")
            return Env(data=[{"name": n} for n in self.series])
        return Env(data=list(self.series.get(indicators[0], [])))


async def no_raw(user_id: str, indicator: str, start: date, end: date) -> tuple[Any, ...]:
    return ()


def test_family_names_ignore_the_source_suffix() -> None:
    catalog = ["dailySteps", "dailyTotalSteps.apple_health_export", "stepsCadence", "bodyMasss"]
    assert candidates(catalog, ("dailySteps", "dailyTotalSteps")) == (
        "dailySteps", "dailyTotalSteps", "dailyTotalSteps.apple_health_export")  # fmt: skip


def test_merge_prefers_the_newest_source_on_the_same_day() -> None:
    old = tuple((date(2026, 9, 1) + timedelta(days=i), 9000.0) for i in range(20))
    new = ((date(2026, 9, 20), 5000.0), (date(2026, 10, 21), 8700.0))
    merged = merge([old, new])
    assert merged[-1] == (date(2026, 10, 21), 8700.0) and dict(merged)[date(2026, 9, 20)] == 5000.0
    assert len(merged) == 21


def test_imported_apple_data_shows_up_next_to_older_data() -> None:
    svc = FakeHealth(
        {
            "dailySteps": days(date(2026, 4, 1), [9000.0] * 160, "count"),
            "dailyTotalSteps.apple_health_export": days(
                date(2026, 10, 12), [6000.0 + 300 * i for i in range(10)], "{#}"
            ),
            "dailyTotalSleepAnalysis_Asleep(Total).apple_health_export": days(
                date(2026, 10, 11), [26_400_000.0] * 10, "ms"
            ),
        }
    )

    async def hrv(user_id: str, indicator: str, start: date, end: date) -> tuple[Any, ...]:
        return (
            tuple((date(2026, 10, 12) + timedelta(days=i), 48.0 + i) for i in range(10))
            if indicator == "hrvSDNN"
            else ()
        )

    r = asyncio.run(read_all(svc, "105", TODAY, raw=hrv))
    assert r.steps[-1] == (date(2026, 10, 21), 8700.0) and r.steps[0][1] == 9000.0
    assert r.sleep_hours[-1] == (date(2026, 10, 20), 26_400_000.0 / 3_600_000)  # 毫秒换成小时
    assert r.hrv_sdnn[-1] == (date(2026, 10, 21), 57.0) and not r.errors


def test_unknown_sleep_units_are_not_guessed() -> None:
    svc = FakeHealth({"sleepDuration": days(date(2026, 10, 1), [7.0, 8.0], "furlongs")})
    assert asyncio.run(read_all(svc, "1", TODAY, raw=no_raw)).sleep_hours == ()


def test_fixed_names_still_work_without_the_catalog() -> None:
    svc = FakeHealth({"bodyMasss": days(date(2026, 9, 1), [69.0, 69.2], "kg")}, catalog_fails=True)
    r = asyncio.run(read_all(svc, "1", TODAY, raw=no_raw))
    assert r.weight == ((date(2026, 9, 1), 69.0), (date(2026, 9, 2), 69.2))
