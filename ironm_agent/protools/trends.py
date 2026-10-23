"""趋势分析：按指定的指标和时间范围，算头尾一周的平均、每周变化、最高最低，并判断变化是否超过日常波动。"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from datetime import date, timedelta

from ironm_agent.metrics import Point, Readings
from ironm_agent.protools.result import Finding, Result

MIN_DAYS, MAX_DAYS = 7, 180
EDGE = 7  # 头、尾各取一周
MIN_SPAN = 14  # 至少跨 2 周才比较头尾
SIGNIFICANT = 2.0  # 头尾平均之差超过 2 倍标准误才算真实变化

# 指标 → (名字, 单位, 小数位, 用哪一列)
INDICATORS: dict[str, tuple[str, str, int]] = {
    "weight": ("体重", "公斤", 1),
    "resting_hr": ("静息心率", "次/分", 0),
    "hrv_sdnn": ("心率变异性（SDNN）", "毫秒", 0),
    "hrv_rmssd": ("心率变异性（RMSSD）", "毫秒", 0),
    "sleep_hours": ("睡眠时长", "小时", 1),
    "steps": ("步数", "步", 0),
    "systolic": ("收缩压", "mmHg", 0),
    "diastolic": ("舒张压", "mmHg", 0),
}


def series(readings: Readings, indicator: str) -> tuple[Point, ...]:
    value = getattr(readings, indicator, ())
    return value if isinstance(value, tuple) else ()


def _f(x: float, places: int) -> str:
    return f"{x:.{places}f}"


def _slope(points: Sequence[Point]) -> tuple[float, float]:
    """最小二乘的每天变化量，以及残差的标准差。"""
    t0 = points[0][0]
    xs = [(d - t0).days for d, _ in points]
    ys = [v for _, v in points]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return 0.0, statistics.pstdev(ys)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx
    residuals = [y - (my + b * (x - mx)) for x, y in zip(xs, ys, strict=True)]
    sd = statistics.stdev(residuals) if len(residuals) > 2 else 0.0
    return b, sd


def trend(points: Sequence[Point], today: date, *, indicator: str, days: int) -> Result:
    if indicator not in INDICATORS:
        return Result.note(
            "不认识这个指标；可以用：" + "、".join(n for n, _, _ in INDICATORS.values())
        )
    name, unit, places = INDICATORS[indicator]
    days = max(MIN_DAYS, min(MAX_DAYS, days))
    start = today - timedelta(days=days - 1)
    window = sorted((p for p in points if start <= p[0] <= today), key=lambda p: p[0])
    data = f"{start.isoformat()} 到 {today.isoformat()} 的{name}记录 {len(window)} 条"
    if not window:
        return Result.note(f"最近 {days} 天没有{name}记录，不能推测为正常，也不能给数字。")
    span = (window[-1][0] - window[0][0]).days + 1
    values = [v for _, v in window]
    low = min(window, key=lambda p: p[1])
    high = max(window, key=lambda p: p[1])
    summary = Finding(
        f"{name}（最近 {days} 天）",
        f"平均 {_f(statistics.fmean(values), places)} {unit}，最低 {_f(low[1], places)}（{low[0].isoformat()}），"
        f"最高 {_f(high[1], places)}（{high[0].isoformat()}）",
        "按天的记录求平均，取最低和最高",
        data,
    )
    if span < MIN_SPAN:
        return Result(
            (summary,),
            notes=(f"记录只跨了 {span} 天，至少要 {MIN_SPAN} 天才能比较头尾、判断有没有变化。",),
        )
    head = [v for d, v in window if d < window[0][0] + timedelta(days=EDGE)]
    tail = [v for d, v in window if d > window[-1][0] - timedelta(days=EDGE)]
    first, last = statistics.fmean(head), statistics.fmean(tail)
    change = last - first
    per_day, sd = _slope(window)
    se = sd * math.sqrt(1 / len(head) + 1 / len(tail)) if sd else 0.0
    real = abs(change) > SIGNIFICANT * se if se else change != 0
    if not real:
        verdict = "变化没有超过日常波动，算基本持平"
    else:
        verdict = "上升" if change > 0 else "下降"
        verdict = f"明显{verdict}（超过了日常波动）"
    # 数字不带正负号，用"多 / 少"写方向：回答里写"少了 0.6 公斤"也能对上
    change_text = f"{'多' if change >= 0 else '少'} {_f(abs(change), places)}"
    weekly = per_day * 7
    weekly_text = f"{'增加' if weekly >= 0 else '减少'} {_f(abs(weekly), places)}"
    return Result(
        (
            summary,
            Finding(
                f"{name}的变化（最近 {days} 天）",
                f"头一周平均 {_f(first, places)}，最后一周平均 {_f(last, places)}，最后一周{change_text} {unit}，"
                f"大约每周{weekly_text} {unit}；{verdict}",
                f"头、尾各取 {EDGE} 天的平均相减；每周变化用全部记录的最小二乘直线斜率 × 7；"
                f"相差超过日常波动（直线残差）的 {SIGNIFICANT:g} 倍标准误才算真实变化",
                data,
            ),
        )
    )
