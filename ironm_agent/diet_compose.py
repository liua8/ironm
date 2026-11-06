"""饮食自动组合（spec [2026-11-06] §192）：管家挑工作日、周末各四顿吃什么，系统按食物库算营养、定每顿几份、检查。

挑什么由模型判断（他的忌口、吃饭场景、口味）；这里只算和查：
- 每顿是推荐食谱（recipe:编号）、他自建的食谱（mine:编号）或常见减脂餐（preset:编号）；
- 食谱每顿 0.5–3 份、取 0.5 的倍数，减脂餐一整份不动；挑一天热量最接近目标的份数（一样近取蛋白质多的）；
- 一天热量在目标 ±8% 以内、蛋白质不低于目标的 90%、脂肪占热量 20–35%、没有他不吃的东西。
没过的把哪一天差多少、哪顿有问题写清楚，交还给管家改了再交。不调用模型、不读写存储。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import product
from typing import Any

from ironm_agent.diet_library import MAX_SERVINGS, MIN_SERVINGS, SET_NAMES, STEP
from ironm_agent.foods import Food, by_id
from ironm_agent.meals import Macros, preset_meal, presets
from ironm_agent.recipes import SLOTS, Recipe, SlotRef, recommended

KCAL_BAND = 0.08  # 一天热量在目标上下 8% 以内
PROTEIN_FLOOR = 0.9  # 蛋白质不低于目标的 90%
FAT_SHARE = (0.20, 0.35)  # 脂肪占热量（K124、K17 的 20–30%，多给一点余量给外卖）

_DAIRY = {"milk", "skim-milk", "lowfat-milk", "yogurt-plain", "yogurt-sweet", "greek-yogurt", "cheese", "whey",
          "latte", "milk-tea", "butter", "ice-cream", "cake"}  # fmt: skip
_EGGS = {"egg", "egg-white"}
# 他说"不吃 X"时，X 这个说法包括哪些食物（名字里看不出来的：五花肉是猪肉、乳清蛋白粉是奶）
GROUPS: dict[str, Callable[[Food], bool]] = {
    "猪肉": lambda f: f.id.startswith("pork") or f.id in ("dumplings",),
    "牛肉": lambda f: "牛" in f.name and f.cat == "肉蛋",
    "羊肉": lambda f: "羊" in f.name,
    "鸡肉": lambda f: "鸡" in f.name and f.cat == "肉蛋" and f.id not in _EGGS,
    "肉": lambda f: f.cat == "肉蛋" and f.id not in _EGGS,
    "海鲜": lambda f: f.cat == "水产",
    "水产": lambda f: f.cat == "水产",
    "鱼": lambda f: f.cat == "水产" and "虾" not in f.name and f.id != "squid",
    "虾": lambda f: "虾" in f.name,
    "蛋": lambda f: f.id in _EGGS,
    "奶": lambda f: f.id in _DAIRY or "奶" in f.name,
    "乳制品": lambda f: f.id in _DAIRY,
    "乳糖": lambda f: f.id in _DAIRY - {"whey", "butter", "cheese"},
    "花生": lambda f: "花生" in f.name,
    "坚果": lambda f: f.cat == "坚果油" and f.id not in ("oil", "butter", "sugar"),
    "豆制品": lambda f: f.cat == "奶豆" and f.id not in _DAIRY,
    "大豆": lambda f: f.cat == "奶豆" and f.id not in _DAIRY,
    "麸质": lambda f: any(w in f.name for w in ("面", "麦", "馒头", "包", "饺子", "吐司", "油条", "饼")),
    "小麦": lambda f: any(w in f.name for w in ("面", "麦", "馒头", "包", "饺子", "吐司", "油条", "饼")),
}
_ALIASES = {"猪": "猪肉", "牛": "牛肉", "羊": "羊肉", "鸡": "鸡肉", "牛奶": "奶", "奶制品": "乳制品", "鸡蛋": "蛋",
            "鱼虾": "海鲜", "豆腐": "豆制品", "荤": "肉"}  # fmt: skip


@dataclass(frozen=True)
class Dish:
    """一顿的候选：一份的营养、能不能加减份数、里面有什么（查忌口用）。"""

    ref: SlotRef
    name: str
    per: Macros  # 一份
    scalable: bool
    foods: tuple[Food, ...]  # 用到的原料（菜品展开成原料）
    text: str = ""  # 减脂餐：写在 items 里的说法


def _expand(fid: str) -> list[Food]:
    lib = by_id()
    f = lib.get(fid)
    if f is None:
        return []
    out = [f]
    if f.dish:
        names = {x.name: x.id for x in lib.values()}
        for name, _ in f.parts:
            out += _expand(names.get(name, name))
    return out


def _recipe_dish(r: Recipe) -> Dish:
    foods = tuple(x for p in r.parts for x in _expand(p.food_id))
    ref = SlotRef(type="mine" if r.mine else "recipe", id=r.id, servings=1)
    return Dish(ref, r.name, r.per_serving(), True, foods)


def resolve(code: str, mine: Sequence[Recipe] = ()) -> Dish | None:
    """recipe:编号、mine:编号、preset:编号 → 候选；不认识的 None。"""
    kind, _, rid = str(code).strip().partition(":")
    if kind == "recipe":
        r = next((x for x in recommended() if x.id == rid), None)
        return _recipe_dish(r) if r else None
    if kind == "mine":
        r = next((x for x in mine if x.id == rid), None)
        return _recipe_dish(r) if r else None
    if kind == "preset":
        p = next((x for x in presets() if x.id == rid), None)
        if p is None:
            return None
        m = preset_meal(p, "午餐")
        return Dish(SlotRef(type="preset", id=p.id, servings=1), p.name, m.macros, False, (),
                    text=p.name + "、" + "、".join(p.items))  # fmt: skip
    return None


def avoided(d: Dish, avoid: Iterable[str]) -> list[str]:
    """这顿里有他不吃的哪几样（返回他说的那个词）。"""
    hits = []
    for word in (w.strip() for w in avoid if w and w.strip()):
        key = _ALIASES.get(word, word)
        test = GROUPS.get(key)
        found = any((test(f) if test else (word in f.name or any(word in a for a in f.aka))) for f in d.foods)
        found = found or word in d.name or (key in d.text if test is None else word in d.text)
        if found:
            hits.append(word)
    return hits


@dataclass(frozen=True)
class Sum:
    kcal: float
    protein_g: float
    fat_g: float


def _total(dishes: Sequence[Dish], servings: Sequence[float]) -> Sum:
    k = p = f = 0.0
    for d, s in zip(dishes, servings, strict=True):
        k, p, f = k + d.per.kcal * s, p + d.per.protein_g * s, f + d.per.fat_g * s
    return Sum(k, p, f)


def _grid(x: float) -> float:
    return min(MAX_SERVINGS, max(MIN_SERVINGS, x))


def fit(dishes: Sequence[Dish], kcal: float | None) -> list[float]:
    """每顿几份：和方案库套用一样，能加减的几顿按同一个比例放大缩小（不会早餐半份、晚餐三份），
    每顿在比例上下各取一个 0.5 的倍数，挑一天热量最接近目标的组合（一样近取离比例最近的）；减脂餐一整份。"""
    if not kcal:
        return [1.0] * len(dishes)
    fixed = sum(d.per.kcal for d in dishes if not d.scalable)
    flex = sum(d.per.kcal for d in dishes if d.scalable)
    if not flex:
        return [1.0] * len(dishes)
    factor = max(0.0, kcal - fixed) / flex
    options = [sorted({_grid(math.floor(factor / STEP) * STEP), _grid(math.ceil(factor / STEP) * STEP)})
               if d.scalable else [1.0] for d in dishes]  # fmt: skip
    best: tuple[tuple[int, float], list[float]] | None = None
    for combo in product(*options):
        gap = round(abs(_total(dishes, combo).kcal - kcal) / 10)
        drift = sum(abs(s - factor) for s, d in zip(combo, dishes, strict=True) if d.scalable)
        if best is None or (gap, drift) < best[0]:
            best = ((gap, drift), list(combo))
    assert best is not None
    return best[1]


@dataclass(frozen=True)
class Day:
    dishes: dict[str, Dish]
    servings: dict[str, float]
    total: Sum
    problems: tuple[str, ...]


def check_day(name: str, dishes: Mapping[str, Dish], kcal: float | None, protein: float | None,
              avoid: Sequence[str]) -> Day:  # fmt: skip
    kinds = list(dishes)
    servings = dict(zip(kinds, fit([dishes[k] for k in kinds], kcal), strict=True))
    total = _total([dishes[k] for k in kinds], [servings[k] for k in kinds])
    problems = []
    if kcal and abs(total.kcal - kcal) > kcal * KCAL_BAND:
        way = "多" if total.kcal > kcal else "少"
        problems.append(f"{name}份数调到头一天也只能到约 {round(total.kcal)} 千卡，比目标 {round(kcal)} 千卡{way}"
                        f" {round(abs(total.kcal - kcal))}：换{'热量低' if way == '多' else '热量高'}一点的菜")  # fmt: skip
    if protein and total.protein_g < protein * PROTEIN_FLOOR:
        low = min(kinds, key=lambda k: dishes[k].per.protein_g * servings[k])
        problems.append(f"{name}蛋白质约 {round(total.protein_g)} 克，目标约 {round(protein)} 克：把{low}"
                        f"（{dishes[low].name}）换成蛋白质多的")  # fmt: skip
    if total.kcal:
        share = total.fat_g * 9 / total.kcal
        if not FAT_SHARE[0] <= share <= FAT_SHARE[1]:
            fat = max(kinds, key=lambda k: dishes[k].per.fat_g * servings[k])
            problems.append(f"{name}脂肪占热量 {share:.0%}（要在 {FAT_SHARE[0]:.0%}–{FAT_SHARE[1]:.0%}）："
                            + (f"{fat}（{dishes[fat].name}）油最多，换清淡的" if share > FAT_SHARE[1]
                               else "太素了，加点鱼、蛋、坚果"))  # fmt: skip
    for k in kinds:
        if hit := avoided(dishes[k], avoid):
            problems.append(f"{name}{k}（{dishes[k].name}）里有他不吃的{'、'.join(hit)}：换掉")
    return Day(dict(dishes), servings, total, tuple(problems))


@dataclass(frozen=True)
class Composed:
    ok: bool
    problems: tuple[str, ...]
    days: dict[str, Day]

    def raw(self) -> dict[str, Any]:
        """写成饮食计划的样子（同 §118 的饮食计划）。"""
        return {s: {k: d.dishes[k].ref.model_copy(update={"servings": d.servings[k]}).model_dump(mode="json")
                    for k in SLOTS} for s, d in self.days.items()}  # fmt: skip

    def lines(self) -> list[str]:
        out = []
        for s, d in self.days.items():
            meals = "、".join(f"{k}{d.dishes[k].name}" + (f"（{d.servings[k]:g} 份）" if d.servings[k] != 1 else "")
                              for k in SLOTS)  # fmt: skip
            out.append(f"{SET_NAMES[s]}：{meals}；一天约 {round(d.total.kcal)} 千卡、蛋白质 {round(d.total.protein_g)} 克")
        return out


def compose(args: Mapping[str, Any], kcal: float | None, protein: float | None, mine: Sequence[Recipe] = (),
            avoid: Sequence[str] = ()) -> Composed:  # fmt: skip
    """args：{"weekday": {"早餐": "recipe:…", …}, "weekend": {…}}；周末没写就和工作日一样。"""
    problems: list[str] = []
    days: dict[str, Day] = {}
    week = args.get("weekday") if isinstance(args.get("weekday"), Mapping) else {}
    end = args.get("weekend") if isinstance(args.get("weekend"), Mapping) else None
    for s, given in (("weekday", week), ("weekend", end if end else week)):
        name = SET_NAMES[s]
        dishes: dict[str, Dish] = {}
        for k in SLOTS:
            code = (given or {}).get(k)
            if not code:
                problems.append(f"{name}{k}没写：四顿都要有")
                continue
            d = resolve(str(code), mine)
            if d is None:
                problems.append(f"{name}{k}的「{code}」不认识：写 recipe:、mine: 或 preset: 加编号（先不带参数调一次看清单）")
                continue
            dishes[k] = d
        if len(dishes) == len(SLOTS):
            day = check_day(name, dishes, kcal, protein, avoid)
            days[s] = day
            problems += day.problems
    return Composed(not problems and len(days) == 2, tuple(problems), days)


def menu(mine: Sequence[Recipe] = ()) -> str:
    """候选清单：编号、名字、标签、一份多少千卡和蛋白质。"""
    def row(code: str, name: str, tags: Iterable[str], m: Macros) -> str:
        t = "、".join(tags)
        return f"- {code} {name}（{t + '；' if t else ''}一份约 {round(m.kcal)} 千卡、蛋白质 {round(m.protein_g)} 克）"

    lines = ["推荐食谱（recipe:编号，每顿 0.5–3 份，系统按热量目标定份数）："]
    lines += [row(f"recipe:{r.id}", r.name, r.tags, r.per_serving()) for r in recommended()]
    if mine:
        lines.append("他自建的食谱（mine:编号）：")
        lines += [row(f"mine:{r.id}", r.name, r.tags, r.per_serving()) for r in mine]
    lines.append("常见减脂餐（preset:编号，外卖、食堂、便利店，一整份不缩放）：")
    lines += [row(f"preset:{p.id}", p.name, [p.scene], preset_meal(p, "午餐").macros) for p in presets()]
    return "\n".join(lines)
