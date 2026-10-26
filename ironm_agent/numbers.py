"""数字核对：回答里的数字能否在依据里找到（允许按依据四舍五入、两个依据数值之差）。"""

from __future__ import annotations

import re
from collections.abc import Iterable


class Written(float):
    """写出来的数值，记着写了几位小数："6.0" 是一位小数，核对时不能拿 5.6 四舍五入成 6 来对上（spec [2026-10-23] §37）。"""

    places: int

    def __new__(cls, value: float, places: int) -> Written:
        out = super().__new__(cls, value)
        out.places = places
        return out


_TOKEN = re.compile(r"\d+(?:\.\d+)?")


def written_numbers(text: str) -> list[float]:
    """文字里写出的数值（日期、时间、年份不算，沿用 mirobody 的认法），每个记着原文写了几位小数。"""
    from mirobody.kernel.citations import numbers

    tokens = [(float(t), len(t.split(".")[1]) if "." in t else 0) for t in _TOKEN.findall(text)]
    out: list[float] = []
    start = 0
    for v in numbers(text):
        i = next(
            (j for j in range(start, len(tokens)) if abs(tokens[j][0] - float(v)) < 1e-9), None
        )
        if i is None:
            out.append(float(v))
            continue
        out.append(Written(float(v), tokens[i][1]))
        start = i + 1
    return out


def _decimals(value: float) -> int:
    if isinstance(value, Written):
        return value.places
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return len(text.split(".")[1]) if "." in text else 0


def traced(
    value: float,
    sources: Iterable[float],
    *,
    data: Iterable[float] = (),
    coefs: Iterable[float] = (),
) -> bool:
    """value 能否追溯到依据（都按 value 写出的小数位四舍五入）：

    - 等于某个依据数值（sources，含 data 与 coefs）；
    - 等于两个数据值之差、之比（"比去年低了 2 次"）；
    - 等于数据值乘以资料里的系数（"按 69.2 公斤 × 0.3 克/公斤 ≈ 21 克"）。
    资料自身的数字只认原值，不拿来互相加减乘除，免得数字多的资料凑出任意数。
    """
    places = _decimals(value)

    def same(x: float) -> bool:
        return round(x, places) == value or abs(x - value) < 1e-9

    data_pool = list(dict.fromkeys(data))
    coef_pool = list(dict.fromkeys(coefs))
    if any(same(v) for v in (*sources, *data_pool, *coef_pool)):
        return True
    for i, a in enumerate(data_pool):
        for b in data_pool[i + 1 :]:
            if same(abs(a - b)) or (b and same(a / b)) or (a and same(b / a)):
                return True
    return any(same(d * c) for d in data_pool for c in coef_pool)
