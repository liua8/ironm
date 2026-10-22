"""数字核对：回答里的数字能否在依据里找到（允许按依据四舍五入、两个依据数值之差）。"""

from __future__ import annotations

from collections.abc import Iterable


def written_numbers(text: str) -> list[float]:
    """文字里写出的数值（日期、时间、年份不算）。"""
    from mirobody.kernel.citations import numbers

    return [float(v) for v in numbers(text)]


def _decimals(value: float) -> int:
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return len(text.split(".")[1]) if "." in text else 0


def traced(value: float, sources: Iterable[float]) -> bool:
    """value 等于某个依据数值（按 value 写出的小数位四舍五入），或等于两个依据数值之差。"""
    pool = list(dict.fromkeys(sources))
    places = _decimals(value)
    for v in pool:
        if round(v, places) == value or abs(v - value) < 1e-9:
            return True
    for i, a in enumerate(pool):
        for b in pool[i + 1 :]:
            if round(abs(a - b), places) == abs(value):
                return True
    return False


def untraced(text: str, sources: Iterable[float]) -> list[float]:
    pool = list(sources)
    return [v for v in written_numbers(text) if not traced(v, pool)]
