"""从 mirobody 读计算指标要用的数据：每天一个值的序列与最新的身高。只读，不写。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import date, timedelta
from typing import Any

from ironm_agent.metrics import Point, Readings

_log = logging.getLogger("ironm_agent.healthdata")

WINDOW_DAYS = 180  # 往回读多久；mirobody 按天汇总时每个指标最多返回最近 92 个点

# 同一类数据在不同来源里名字不同：设备或种子数据按天汇总叫 dailySteps，苹果健康导入后叫
# dailyTotalSteps.apple_health_export（点后面是来源）。先查这个人的指标目录，按去掉来源后的名字认出
# 同一类的所有来源，再按日期合并：同一天取数据最新的那个来源（换了设备、导入了新数据时用新的）。
FAMILIES: dict[str, tuple[str, ...]] = {
    "weight": ("bodyMasss", "bodyMass"),
    "resting_hr": ("restingHeartRates", "dailyRestingHeartRates", "dailyAvgRestingHeartRate"),
    "hrv_sdnn": ("hrvSDNN", "dailyAvgHrvSDNN"),
    "hrv_rmssd": ("hrvRMSSD", "dailyAvgHrvRMSSD"),
    "steps": ("dailySteps", "dailyTotalSteps", "steps"),
    "systolic": ("systolicPressures",),
    "diastolic": ("diastolicPressures",),
    # 身体成分与活动（spec [2026-10-23] §26）：mirobody 已有这些指标
    "lean_mass": ("bodyFatFreeWeight",),
    "active_kcal": ("activeCalories", "dailyCaloriesActive"),
    "exercise_min": ("exerciseMinutes",),
    "vo2max": ("vo2Maxs",),
}
# 体脂率：有的来源记成小数（0.185），有的记成百分数（18.5），统一成百分数
# 手动记的"体脂率"会统一到标准编码（LOINC 41982-0），目录里叫 Percentage of body fat Measured
BODY_FAT = ("bodyFatPercentages", "Percentage of body fat Measured")
# 腰围：苹果健康按米记，手动记录按厘米，统一成厘米
WAIST = ("waistCircumferences",)
_TO_CM = {"m": 100.0, "cm": 1.0, "mm": 0.1}
# 睡眠：各家叫法不同，单位也不同（小时、分钟、毫秒），按单位换成小时
SLEEP = (
    "sleepDuration",
    "dailyTotalSleepTime",
    "dailyTotalSleepAnalysis_Asleep(Total)",
    "sleepAnalysis_Asleep(Total)",
    "dailySleepDuration",
    "totalSleepTime",
)
# mirobody 没有按天汇总的（苹果健康导入的心率变异性），从原始读数按天求平均
RAW_DAILY = {"hrv_sdnn": "hrvSDNN", "hrv_rmssd": "hrvRMSSD"}
_TO_HOURS = {"h": 1.0, "hr": 1.0, "hours": 1.0, "min": 1 / 60, "s": 1 / 3600, "ms": 1 / 3_600_000}


def _float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value).split()[0])
    except (ValueError, IndexError):
        return None


def _points(envelope: Any, scale: Mapping[str, float] | None = None) -> tuple[Point, ...]:
    out: list[Point] = []
    for row in getattr(envelope, "data", None) or []:
        if not isinstance(row, Mapping):
            continue
        avg, period = _float(row.get("avg")), str(row.get("period") or "")[:10]
        if avg is None or len(period) != 10:
            continue
        factor = 1.0
        if scale is not None:
            factor = scale.get(str(row.get("unit") or "").strip().lower(), 0.0)
            if not factor:
                continue  # 单位认不出就不用，免得把毫秒当小时
        out.append((date.fromisoformat(period), avg * factor))
    return tuple(sorted(out))


async def _series(svc: Any, who: Mapping[str, str], name: str, start: date, end: date,
                  scale: Mapping[str, float] | None = None) -> tuple[Point, ...]:  # fmt: skip
    envelope = await svc.envelope(
        who, indicators=[name], view="day", start=start.isoformat(), end=end.isoformat()
    )
    if getattr(envelope, "status", "ok") == "error":
        raise LookupError(name)
    return _points(envelope, scale)


async def _height_cm(svc: Any, who: Mapping[str, str]) -> float | None:
    envelope = await svc.envelope(who, indicators=["heights"], view="latest")
    for row in getattr(envelope, "data", None) or []:
        value = _float(row.get("value")) if isinstance(row, Mapping) else None
        if value is None:
            continue
        unit = str(row.get("unit") or "").lower()
        return value * 100 if unit == "m" or value < 3 else value
    return None


def _family(name: str) -> str:
    """去掉来源后缀：dailyTotalSteps.apple_health_export → dailytotalsteps。"""
    return name.split(".")[0].strip().lower()


def candidates(catalog: list[str], known: tuple[str, ...]) -> tuple[str, ...]:
    """这一类数据要读的名字：固定的候选名，加上目录里同一类的其他来源。"""
    want = {k.lower() for k in known}
    found = [n for n in catalog if _family(n) in want]
    return tuple(dict.fromkeys([*known, *found]))


def merge(series: list[tuple[Point, ...]]) -> tuple[Point, ...]:
    """几个来源按日期合并；同一天有好几个来源时，取最后一条记录最新的那个来源（再看记录多少）。"""
    ranked = sorted((s for s in series if s), key=lambda s: (s[-1][0], len(s)), reverse=True)
    by_day: dict[date, float] = {}
    for s in ranked:
        for day, value in s:
            by_day.setdefault(day, value)
    return tuple(sorted(by_day.items()))


async def _catalog(svc: Any, who: Mapping[str, str]) -> list[str]:
    """这个人有哪些指标（只要名字）；读不到时返回空列表，按固定候选名照常读。"""
    try:
        envelope = await svc.envelope(who)
    except Exception as e:
        _log.warning("catalog unavailable: error_type=%s", type(e).__name__)
        return []
    rows = getattr(envelope, "data", None) or []
    return [str(r["name"]) for r in rows if isinstance(r, Mapping) and r.get("name")]


_RAW_SQL = """
SELECT (time AT TIME ZONE 'UTC' AT TIME ZONE COALESCE(NULLIF(timezone, ''), 'UTC'))::date AS day,
       avg(CASE WHEN value ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN value::double precision END) AS avg
  FROM series_data
 WHERE user_id = :user_id AND indicator = :indicator AND time >= :start AND time < :end
 GROUP BY 1
 ORDER BY 1
"""


async def raw_daily(user_id: str, indicator: str, start: date, end: date) -> tuple[Point, ...]:
    """原始读数按本地日期求每天的平均（mirobody 没有为它做按天汇总时用）。"""
    from mirobody.utils.db import execute_query

    rows = await execute_query(
        _RAW_SQL,
        {
            "user_id": user_id,
            "indicator": indicator,
            "start": start,
            "end": end + timedelta(days=1),
        },
        log_sql=False,
    )
    out = [(r["day"], float(r["avg"])) for r in rows or [] if r.get("avg") is not None]
    return tuple(sorted(out))


async def read_all(
    svc: Any,
    user_id: str,
    today: date,
    raw: Callable[[str, str, date, date], Awaitable[tuple[Point, ...]]] = raw_daily,
) -> Readings:
    """读全部数据；某一项读不到时记下来，其余照常。"""
    who = {"user_id": user_id}
    start = today - timedelta(days=WINDOW_DAYS)
    catalog = await _catalog(svc, who)
    names = {k: candidates(catalog, known) for k, known in FAMILIES.items()}
    keys = [(k, n) for k, ns in names.items() for n in ns]
    results = await asyncio.gather(
        *(_series(svc, who, n, start, today) for _, n in keys), return_exceptions=True
    )
    found: dict[str, list[tuple[Point, ...]]] = {k: [] for k in names}
    failures: dict[str, int] = {}
    for (key, _), result in zip(keys, results, strict=True):
        if isinstance(result, BaseException):
            _log.warning("series unavailable: key=%s error_type=%s", key, type(result).__name__)
            failures[key] = failures.get(key, 0) + 1
        else:
            found[key].append(result)
    for key, indicator in RAW_DAILY.items():
        try:
            found[key].append(await raw(user_id, indicator, start, today))
        except Exception as e:
            _log.warning("raw series unavailable: key=%s error_type=%s", key, type(e).__name__)
    errors = [k for k, n in failures.items() if n == len(names[k]) and not any(found[k])]
    got = {k: merge(v) for k, v in found.items()}
    sleep_names = candidates(catalog, SLEEP)
    sleep_parts = await asyncio.gather(
        *(_series(svc, who, n, start, today, _TO_HOURS) for n in sleep_names),
        return_exceptions=True,
    )
    sleep = merge([x for x in sleep_parts if not isinstance(x, BaseException)])
    waist_parts = await asyncio.gather(
        *(_series(svc, who, n, start, today, _TO_CM) for n in candidates(catalog, WAIST)),
        return_exceptions=True,
    )
    waist = merge([x for x in waist_parts if not isinstance(x, BaseException)])
    fat_parts = await asyncio.gather(
        *(_series(svc, who, n, start, today) for n in candidates(catalog, BODY_FAT)),
        return_exceptions=True,
    )
    body_fat = tuple(
        (d, v * 100 if v <= 1 else v)
        for d, v in merge([x for x in fat_parts if not isinstance(x, BaseException)])
    )
    try:
        height = await _height_cm(svc, who)
    except Exception as e:
        _log.warning("height unavailable: error_type=%s", type(e).__name__)
        height = None
    return Readings(sleep_hours=sleep, height_cm=height, waist=waist, body_fat=body_fat,
                    errors=tuple(errors), **got)  # fmt: skip
