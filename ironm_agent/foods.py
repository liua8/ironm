"""常见食物库（spec [2026-10-23] §118 需求 1–3）：按名字查、按克数和油量算营养，不调用模型。

原料写每 100 克的营养；菜品只写原料（生重）和油，每 100 克由这里按原料算（按原料加油的总重，没算烹调中
水分的变化）。油量：少油 ×0.5、正常 ×1、多油 ×1.5（经验）。库里没有的，用模型给的每 100 克估值，标出来。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Literal

from ironm_agent.yamlfile import load_yaml

FOODS_PATH = Path(__file__).with_name("foods.yaml")
type Oil = Literal["少油", "正常", "多油"]
OIL_FACTOR: dict[str, float] = {"少油": 0.5, "正常": 1.0, "多油": 1.5}
OIL_ID = "oil"
MAX_GRAMS = 3000


@dataclass(frozen=True)
class Per100:
    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float

    def times(self, k: float) -> Per100:
        return Per100(self.kcal * k, self.protein_g * k, self.carbs_g * k, self.fat_g * k)

    def plus(self, o: Per100) -> Per100:
        return Per100(self.kcal + o.kcal, self.protein_g + o.protein_g,
                      self.carbs_g + o.carbs_g, self.fat_g + o.fat_g)  # fmt: skip


ZERO = Per100(0, 0, 0, 0)


@dataclass(frozen=True)
class Food:
    id: str
    name: str
    aka: tuple[str, ...]
    cat: str
    unit: str  # 一份叫什么
    unit_g: float  # 一份大约多少克
    per100: Per100 | None = None  # 原料
    parts: tuple[tuple[str, float], ...] = ()  # 菜品：原料 id 和克数
    oil: float = 0  # 菜品：正常油量（克）
    alcohol: bool = False

    @property
    def dish(self) -> bool:
        return self.per100 is None

    def nutrition(self, grams: float, oil: str = "正常") -> Per100:
        """吃了 grams 克的营养；菜品按油量算，原料不看油量。"""
        if self.per100 is not None:
            return self.per100.times(grams / 100)
        lib = by_id()
        total = sum(g for _, g in self.parts) + self.oil  # 按正常油量的总重折算
        body = ZERO
        for fid, g in self.parts:
            body = body.plus(lib[fid].nutrition(g))
        fat = lib[OIL_ID].nutrition(self.oil * OIL_FACTOR.get(oil, 1.0))
        return body.plus(fat).times(grams / total) if total else ZERO

    def per_100(self, oil: str = "正常") -> Per100:
        return self.nutrition(100, oil)


@cache
def foods(path: Path = FOODS_PATH) -> tuple[Food, ...]:
    raw: dict[str, Any] = load_yaml(path)  # type: ignore[assignment]
    out: list[Food] = []
    for x in raw["foods"]:
        unit, g = x["unit"]
        out.append(Food(x["id"], x["name"], tuple(x.get("aka") or ()), x["cat"], unit, float(g),
                        per100=Per100(*map(float, x["per100"])), alcohol=bool(x.get("alcohol"))))  # fmt: skip
    names = {f.name: f.id for f in out}
    for x in raw["dishes"]:
        parts = tuple((names[n], float(g)) for n, g in x["parts"].items())  # 原料名写错时这里报错
        total = sum(g for _, g in parts) + float(x["oil"])
        out.append(Food(x["id"], x["name"], tuple(x.get("aka") or ()), x["cat"], x["unit"], total,
                        parts=parts, oil=float(x["oil"])))  # fmt: skip
    ids = [f.id for f in out]
    words = [w for f in out for w in (f.name, *f.aka)]
    if len(ids) != len(set(ids)) or len(words) != len(set(words)):
        raise ValueError("食物库的编号或名字重复")
    return tuple(out)


@cache
def by_id() -> dict[str, Food]:
    return {f.id: f for f in foods()}


_BRACKET = re.compile(r"[（(].*?[)）]")


def find(name: str) -> Food | None:
    """按名字找：先全名和别名，再去掉括号比，最后看名字里包含了哪个（取最长的）。"""
    text = name.strip()
    if not text:
        return None
    exact = {w: f for f in foods() for w in (f.name, *f.aka)}
    if text in exact:
        return exact[text]
    bare = _BRACKET.sub("", text).strip()
    loose = {_BRACKET.sub("", w): f for w, f in exact.items()}
    if bare in loose:
        return loose[bare]
    hits = [(w, f) for w, f in loose.items() if len(w) >= 2 and w in bare]
    return max(hits, key=lambda x: len(x[0]))[1] if hits else None


def search(q: str, limit: int = 20) -> list[Food]:
    """食物库里搜：名字或别名包含这几个字的，全名开头的排前面。"""
    q = q.strip()
    if not q:
        return []
    hits = [f for f in foods() if any(q in w for w in (f.name, *f.aka))]
    return sorted(hits, key=lambda f: (not f.name.startswith(q), len(f.name)))[:limit]
