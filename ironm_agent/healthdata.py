"""从 mirobody 读计算指标要用的数据：每天一个值的序列与最新的身高。只读，不写。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

from ironm_agent.metrics import Point, Readings

_log = logging.getLogger("ironm_agent.healthdata")

WINDOW_DAYS = 180  # 往回读多久；mirobody 按天汇总时每个指标最多返回最近 92 个点

# 睡眠在不同设备里叫法不同，按顺序取第一个有数据的
SLEEP = (
    "sleepDuration",
    "dailyTotalSleepTime",
    "sleepAnalysis_Asleep(Total)",
    "dailySleepDuration",
    "totalSleepTime",
)
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


async def read_all(svc: Any, user_id: str, today: date) -> Readings:
    """读全部数据；某一项读不到时记下来，其余照常。"""
    who = {"user_id": user_id}
    start = today - timedelta(days=WINDOW_DAYS)
    # 同一个指标在不同设备里存的名字不同（按天汇总的叫 daily…），每项列出候选名，取记录最多的那个
    names: dict[str, tuple[str, ...]] = {
        "weight": ("bodyMasss",),
        "resting_hr": ("restingHeartRates", "dailyRestingHeartRates"),
        "hrv_sdnn": ("hrvSDNN",),
        "hrv_rmssd": ("hrvRMSSD",),
        "steps": ("steps", "dailySteps"),
        "systolic": ("systolicPressures",),
        "diastolic": ("diastolicPressures",),
    }
    keys = [(k, n) for k, ns in names.items() for n in ns]
    results = await asyncio.gather(
        *(_series(svc, who, n, start, today) for _, n in keys), return_exceptions=True
    )
    got: dict[str, tuple[Point, ...]] = {k: () for k in names}
    failures: dict[str, int] = {}
    for (key, _), result in zip(keys, results, strict=True):
        if isinstance(result, BaseException):
            _log.warning("series unavailable: key=%s error_type=%s", key, type(result).__name__)
            failures[key] = failures.get(key, 0) + 1
        elif len(result) > len(got[key]):
            got[key] = result
    errors = [k for k, n in failures.items() if n == len(names[k])]
    sleep: tuple[Point, ...] = ()
    for name in SLEEP:
        try:
            sleep = await _series(svc, who, name, start, today, _TO_HOURS)
        except Exception:
            continue
        if sleep:
            break
    try:
        height = await _height_cm(svc, who)
    except Exception as e:
        _log.warning("height unavailable: error_type=%s", type(e).__name__)
        height = None
    return Readings(sleep_hours=sleep, height_cm=height, errors=tuple(errors), **got)
