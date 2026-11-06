"""饮食方案库（spec [2026-11-06] §184）：每份是一整天怎么吃，工作日、周末各四顿，引用推荐食谱或常见减脂餐。

读的时候查：每份四顿都有、食谱和减脂餐都在、依据编号都在依据库里、带数字的句子都有出处、不写商标和品牌。
按热量目标缩放份数、给管家看的目录和单份内容也在这里，只算不读写存储；套用（存进他的饮食计划）在 web_diet_library。
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from functools import cache
from itertools import product
from pathlib import Path
from typing import Literal

from pydantic import Field

from ironm_agent.common import ContractModel
from ironm_agent.kb import default_kb
from ironm_agent.meals import Macros, Meal, MealKind, preset_meal, presets
from ironm_agent.protools.result import Result
from ironm_agent.recipes import SLOTS, PlanSet, recommended

LIBRARY_PATH = Path(__file__).with_name("diet_library.yaml")
SETS: tuple[PlanSet, ...] = ("weekday", "weekend")
SET_NAMES: dict[str, str] = {"weekday": "工作日", "weekend": "周末"}
GOALS: dict[str, str] = {
    "health": "健康", "fat_loss": "减脂", "muscle": "增肌", "blood_pressure": "控血压", "blood_sugar": "控糖",
}  # fmt: skip
MIN_SERVINGS, MAX_SERVINGS, STEP = 0.5, 3.0, 0.5
_MARK = re.compile(r"〔[^〕]*〕")
_KREF = re.compile(r"〔(K\d{2,4})〕")
# 常见的食品、餐饮、便利店品牌：方案库里一个都不能有（§184 约束：不含商标和具体品牌）
BRANDS = (
    "麦当劳", "肯德基", "必胜客", "汉堡王", "赛百味", "星巴克", "瑞幸", "喜茶", "奈雪", "蜜雪冰城", "罗森", "便利蜂",
    "7-11", "美团", "饿了么", "盒马", "蒙牛", "伊利", "君乐宝", "安慕希", "纯甄", "雀巢", "桂格", "康师傅",
    "农夫山泉", "元气森林", "可口可乐", "百事可乐", "乐事", "奥利奥", "旺旺", "良品铺子", "三只松鼠", "百草味", "洽洽",
    "金龙鱼", "鲁花", "海天", "李锦记", "老干妈", "湾仔码头", "Keep", "薄荷健康",
)  # fmt: skip


class Slot(ContractModel):
    """方案里一顿：推荐食谱或常见减脂餐，servings 是推荐份数（0.5 的倍数）。"""

    type: Literal["recipe", "preset"]
    id: str = Field(min_length=1, max_length=60)
    servings: float = Field(default=1, ge=MIN_SERVINGS, le=MAX_SERVINGS, multiple_of=STEP)


class Macro(ContractModel):
    protein: str = Field(min_length=1)
    carbs: str = Field(min_length=1)
    fat: str = Field(min_length=1)


class DietPlan(ContractModel):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    name: str = Field(min_length=1, max_length=20)
    goals: tuple[Literal["health", "fat_loss", "muscle", "blood_pressure", "blood_sugar"], ...] = (
        Field(min_length=1)
    )
    summary: str = Field(min_length=1, max_length=80)
    suits: tuple[str, ...] = Field(min_length=1)
    not_for: tuple[str, ...] = Field(min_length=1)
    energy: str = Field(min_length=1)
    macros: Macro
    points: tuple[str, ...] = Field(min_length=3, max_length=6)
    days: dict[PlanSet, dict[MealKind, Slot]]
    refs: tuple[str, ...] = Field(min_length=1)

    def texts(self) -> list[str]:
        """要查出处的句子（名字和适合谁不查：那里的数字是年龄、几型这类叫法）。"""
        return [self.summary, *self.not_for, self.energy, self.macros.protein, self.macros.carbs,
                self.macros.fat, *self.points]  # fmt: skip

    def every_text(self) -> list[str]:
        return [self.name, *self.suits, *self.texts()]

    def calls(self) -> tuple[str, ...]:
        """点名时认的叫法：编号、全名、去掉括号的名字。"""
        return (self.id, self.name, _MARK.sub("", re.sub(r"[（(].*?[)）]", "", self.name)).strip())


class LibraryFile(ContractModel):
    version: str
    review: str
    plans: tuple[DietPlan, ...] = Field(min_length=1)


def plain(text: str) -> str:
    """给人看的版本：去掉出处编号（追问时才说出处）。"""
    return _MARK.sub("", text).strip()


def _check(p: DietPlan) -> None:
    for s in SETS:
        if set(p.days.get(s, {})) != set(SLOTS):
            raise ValueError(f"{p.id}：{SET_NAMES[s]}要有早餐、午餐、晚餐、加餐四顿")
    rec, pre = {r.id for r in recommended()}, {x.id for x in presets()}
    for s in SETS:
        for slot in p.days[s].values():
            if slot.id not in (rec if slot.type == "recipe" else pre):
                what = "食谱" if slot.type == "recipe" else "减脂餐"
                raise ValueError(f"{p.id}：{SET_NAMES[s]}引用的{what} {slot.id} 不存在")
            if slot.type == "preset" and slot.servings != 1:
                raise ValueError(f"{p.id}：减脂餐是一整份，servings 只能是 1")
    kb = default_kb()
    if bad := [r for r in p.refs if kb.get(r) is None]:
        raise ValueError(f"{p.id}：依据库里没有 {bad}")
    cited = {r for t in p.every_text() for r in _KREF.findall(t)}
    if cited != set(p.refs):
        raise ValueError(
            f"{p.id}：refs 要和正文引用的编号一致（引用了 {sorted(cited)}，写了 {sorted(p.refs)}）"
        )
    if bad := [t for t in p.texts() if re.search(r"\d", t) and not _MARK.search(t)]:
        raise ValueError(f"{p.id}：带数字的句子没写出处：{bad}")
    if bad := [b for b in BRANDS if any(b in t for t in p.every_text())]:
        raise ValueError(f"{p.id}：写了品牌 {bad}")


@cache
def library(path: Path = LIBRARY_PATH) -> tuple[DietPlan, ...]:
    """读方案库；编号或名字重复、四顿不全、引用的食谱不在、依据编号不在、数字没出处、写了品牌，都报错。"""
    from ironm_agent.yamlfile import load_yaml

    plans = LibraryFile.model_validate(load_yaml(path), strict=False).plans
    for key in ("id", "name"):
        vals = [getattr(p, key) for p in plans]
        if len(vals) != len(set(vals)):
            raise ValueError(f"饮食方案的{'编号' if key == 'id' else '名字'}重复")
    for p in plans:
        _check(p)
    return plans


def by_id(plan_id: str) -> DietPlan | None:
    return next((p for p in library() if p.id == plan_id), None)


def named(text: str) -> DietPlan | None:
    """按编号或名字找（他说"地中海"、"DASH"、"控糖"也认）。"""
    text = text.strip()
    if not text:
        return None
    for p in library():
        if text in p.calls() or any(c and (c in text or text in c) for c in p.calls()[1:]):
            return p
    return None


# ---- 每顿吃什么、合计、按热量目标缩放 ----------------------------------------------------------------


def slot_meal(slot: Slot, kind: MealKind, servings: float | None = None) -> Meal:
    """这一顿按几份算（不给就按推荐份数）；减脂餐是一整份。"""
    if slot.type == "preset":
        found = next(x for x in presets() if x.id == slot.id)
        return preset_meal(found, kind)
    r = next(x for x in recommended() if x.id == slot.id)
    return r.meal(kind, slot.servings if servings is None else servings)


def day_total(meals: Mapping[MealKind, Meal]) -> Macros:
    ms = list(meals.values())
    return Macros(
        kcal=round(sum(m.macros.kcal for m in ms)),
        protein_g=round(sum(m.macros.protein_g for m in ms)),
        carbs_g=round(sum(m.macros.carbs_g for m in ms)),
        fat_g=round(sum(m.macros.fat_g for m in ms)),
    )


def day_meals(
    p: DietPlan, s: PlanSet, servings: Mapping[MealKind, float] | None = None
) -> dict[MealKind, Meal]:
    return {k: slot_meal(p.days[s][k], k, (servings or {}).get(k)) for k in SLOTS}


def _half(x: float) -> float:
    return min(MAX_SERVINGS, max(MIN_SERVINGS, x))


def scaled(p: DietPlan, s: PlanSet, target_kcal: float | None) -> dict[MealKind, float]:
    """按他的热量目标定每顿几份：减脂餐一整份不动，其余几顿按比例放大缩小；每顿 0.5–3 份、取 0.5 的倍数。
    每顿在按比例算出的份数上下各取一个 0.5 的倍数，挑一天合计最接近目标的组合（一样近的取离按比例最近的）。"""
    slots = p.days[s]
    base = {k: slots[k].servings for k in SLOTS}
    if not target_kcal or target_kcal <= 0:
        return base
    fixed = sum(slot_meal(x, k).macros.kcal for k, x in slots.items() if x.type == "preset")
    each = {
        k: slot_meal(x, k, 1).macros.kcal for k, x in slots.items() if x.type == "recipe"
    }  # 每份多少千卡
    flex = sum(each[k] * base[k] for k in each)
    if not flex:
        return base
    factor = max(0.0, target_kcal - fixed) / flex
    want = {k: base[k] * factor for k in each}
    choices = {k: sorted({_half(math.floor(v / STEP) * STEP), _half(math.ceil(v / STEP) * STEP)})
               for k, v in want.items()}  # fmt: skip
    keys = list(choices)
    best: tuple[tuple[float, float], dict[MealKind, float]] | None = None
    for combo in product(*(choices[k] for k in keys)):
        pick = dict(zip(keys, combo, strict=True))
        gap = abs(fixed + sum(each[k] * pick[k] for k in keys) - target_kcal)
        drift = sum(abs(pick[k] - want[k]) for k in keys)
        if best is None or (round(gap), drift) < best[0]:
            best = ((round(gap), drift), pick)
    assert best is not None
    return {k: best[1].get(k, base[k]) for k in SLOTS}


def per_day(p: DietPlan) -> dict[str, Macros]:
    """按推荐份数，工作日、周末每天合计多少。"""
    return {s: day_total(day_meals(p, s)) for s in SETS}


def ref_names(p: DietPlan) -> list[str]:
    """依据给人看的样子：资料名、机构、年份（不带编号）。"""
    kb = default_kb()
    return [f"{e.title}（{e.publisher}，{e.year}）" for r in p.refs if (e := kb.get(r)) is not None]


def goal_names(p: DietPlan) -> list[str]:
    return [GOALS[g] for g in p.goals]


# ---- 给管家看的（diet_templates 工具，§184 需求 4）------------------------------------------------------


def catalog() -> Result:
    """方案库一共有哪些：问"有哪些饮食方案"、要排饮食时先看目录。"""
    plans = library()
    lines = [f"- {p.name}（{p.id}）：{'、'.join(goal_names(p))}；适合{plain(p.suits[0])}；{plain(p.summary)}"
             for p in plans]  # fmt: skip
    return Result.note(
        f"饮食方案库一共 {len(plans)} 份（每份是一整天怎么吃，工作日、周末各四顿）：",
        *lines,
        "要看某一份的吃法、要点和一天吃什么，把编号或名字填进 name 再调一次。",
        _HOW_TO_APPLY,
    )


_HOW_TO_APPLY = (
    "推荐时说清是参考方案库的哪一份；他想用，请他在 App 的「图鉴 → 方案 → 饮食方案」里点"
    "「用这份当我的饮食计划」（确认后按他的热量目标换掉工作日、周末四顿，能撤销一次）。"
    "你不要自己改他的饮食计划，也不要说已经替他换好了。孕期、未成年、肾病、糖尿病在用药的不从方案库直接套，先问医生。"
)


def detail(p: DietPlan, target_kcal: float | None = None) -> Result:
    """一份方案的内容（保留出处编号，回答时可以引用）；有热量目标时给按目标缩放后的份数。"""
    notes = [
        f"饮食方案「{p.name}」（{p.id}）：{p.summary}",
        "- 目标：" + "、".join(goal_names(p)),
        "- 适合：" + "；".join(p.suits),
        "- 不适合、要先问医生的：" + "；".join(p.not_for),
        f"- 热量：{p.energy}",
        f"- 蛋白质：{p.macros.protein}",
        f"- 碳水：{p.macros.carbs}",
        f"- 脂肪：{p.macros.fat}",
        *(f"- 要点：{x}" for x in p.points),
    ]
    for s in SETS:
        servings = scaled(p, s, target_kcal)
        meals = day_meals(p, s, servings)
        tot = day_total(meals)
        rows = "；".join(f"{k} {m.name}（{round(m.macros.kcal)} 千卡、蛋白质 {round(m.macros.protein_g)} 克）"
                         for k, m in meals.items())  # fmt: skip
        how = f"按他的热量目标 {round(target_kcal)} 千卡缩放" if target_kcal else "按推荐份数"
        notes.append(
            f"- {SET_NAMES[s]}（{how}）：{rows}。合计 {round(tot.kcal)} 千卡、蛋白质 {round(tot.protein_g)} 克"
        )
    notes += ["营养按食物库算（内容待审定），减脂餐按常见分量估算。", _HOW_TO_APPLY]
    return Result(notes=tuple(notes), entries=p.refs)


def diet_templates(name: str = "", target_kcal: float | None = None) -> Result:
    if not name.strip():
        return catalog()
    p = by_id(name.strip()) or named(name)
    if p is None:
        return Result.note(f"饮食方案库里没有「{name}」。", *catalog().notes)
    return detail(p, target_kcal)
