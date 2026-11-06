"""饮食记录与推荐（spec [2026-10-23] §13）。

- 饮食记录：照片加一句描述，由营养（看图的模型）估算热量和三大营养素，规则核对热量与营养素是否对得上；
- 推荐饮食：营养按目标、今天还差多少、天气、身体状态、胃口、饮食限制推荐一餐，规则核对不超出额度太多；
- 减脂餐：常见搭配（meals.yaml，Claude 整理，待审定），可以一键记为这一餐。

记录和照片只属于本人，用 mirobody 的加密函数加密存储；日志只记次数和错误类型，不记内容。
"""

from __future__ import annotations

import base64
import json
import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from functools import cache
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ironm_agent.common import ContractModel
from ironm_agent.ddl import run_ddl
from ironm_agent.llm import LLM, ModelUnavailable, parse_json
from ironm_agent.yamlfile import load_yaml

_log = logging.getLogger("ironm_agent.meals")

PRESETS_PATH = Path(__file__).with_name("meals.yaml")
MAX_PHOTO_BYTES = 5 * 1024 * 1024
KCAL_TOLERANCE = 0.2  # 热量和"蛋白质×4 + 碳水×4 + 脂肪×9"相差超过 20% 时，按营养素重算
OVER_REMAINING = 1.2  # 推荐一餐的热量超过今天剩余额度的 1.2 倍（且多出 100 千卡以上）就退回

type MealKind = Literal["早餐", "午餐", "晚餐", "加餐", "夜宵", "练前", "练后"]
type Appetite = Literal["清淡", "正常", "很饿"]
# 覆盖全天的餐次；每种餐每天只留一条，再记一次就替换（spec [2026-10-23] §43）
MEAL_KINDS: tuple[MealKind, ...] = ("早餐", "午餐", "晚餐", "加餐", "夜宵", "练前", "练后")


class Macros(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kcal: float = Field(ge=0, le=5000)
    protein_g: float = Field(ge=0, le=400)
    carbs_g: float = Field(ge=0, le=800)
    fat_g: float = Field(ge=0, le=400)

    def from_macros(self) -> float:
        return self.protein_g * 4 + self.carbs_g * 4 + self.fat_g * 9

    def reconciled(self) -> tuple[Macros, bool]:
        """热量和三大营养素对不上时，按营养素重算热量（返回是否改过）。"""
        calc = self.from_macros()
        if calc and abs(self.kcal - calc) > KCAL_TOLERANCE * calc:
            return self.model_copy(update={"kcal": round(calc)}), True
        return self, False

    def rounded(self) -> Macros:
        return Macros(
            kcal=round(self.kcal),
            protein_g=round(self.protein_g),
            carbs_g=round(self.carbs_g),
            fat_g=round(self.fat_g),
        )


class FoodLine(BaseModel):
    """一餐里的一样食物（§118）：库里有的按库算；库里没有的按模型给的每 100 克估值（est100）算。"""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=30)
    grams: float = Field(gt=0, le=3000)
    oil: Literal["少油", "正常", "多油"] = "正常"
    food_id: str | None = None
    est100: Macros | None = None  # 库里没有时模型估的每 100 克
    dish: bool = False  # 菜品（有油量可改）
    macros: Macros


def food_line(
    name: str,
    grams: float,
    oil: str = "正常",
    food_id: str | None = None,
    est100: Macros | None = None,
) -> FoodLine:
    """按食物库算一样食物；库里找不到又没有估值时报 KeyError。"""
    from ironm_agent.foods import by_id, find

    food = by_id().get(food_id) if food_id else find(name)
    oil = oil if oil in ("少油", "正常", "多油") else "正常"
    grams = round(float(grams))
    if food is not None:
        n = food.nutrition(grams, oil)
        m = Macros(kcal=n.kcal, protein_g=n.protein_g, carbs_g=n.carbs_g, fat_g=n.fat_g).rounded()
        return FoodLine(name=food.name, grams=grams, oil=oil if food.dish else "正常",
                        food_id=food.id, dish=food.dish, macros=m)  # fmt: skip
    if est100 is None:
        raise KeyError(name)
    k = grams / 100
    m = Macros(kcal=est100.kcal * k, protein_g=est100.protein_g * k, carbs_g=est100.carbs_g * k,
               fat_g=est100.fat_g * k).rounded()  # fmt: skip
    return FoodLine(name=name[:30], grams=grams, oil="正常", est100=est100, macros=m)


def sum_lines(lines: Sequence[FoodLine]) -> Macros:
    return Macros(
        kcal=round(sum(x.macros.kcal for x in lines)),
        protein_g=round(sum(x.macros.protein_g for x in lines)),
        carbs_g=round(sum(x.macros.carbs_g for x in lines)),
        fat_g=round(sum(x.macros.fat_g for x in lines)),
    )


def line_text(x: FoodLine) -> str:
    return f"{x.name} {x.grams:g} 克" + (f"（{x.oil}）" if x.oil != "正常" else "")


class Meal(BaseModel):
    """一条饮食记录。"""

    model_config = ConfigDict(extra="ignore")

    kind: MealKind = "午餐"
    name: str = Field(min_length=1, max_length=40)
    items: list[str] = Field(default_factory=list, max_length=12)
    macros: Macros
    # 逐样食物（§118），以前的记录没有
    foods: list[FoodLine] = Field(default_factory=list, max_length=12)
    image_key: str = Field(default="", max_length=60)  # 从食谱、减脂餐记的：用它的配图（§119）
    estimated: bool = True  # 照片和描述估算的（减脂餐列表里的也是估算）
    confidence: str = ""  # 低 / 中 / 高
    note: str = Field(default="", max_length=120)
    said: str = Field(default="", max_length=120)  # 用户的描述


def meal_image(meal: Meal) -> dict[str, Any] | None:
    """这一餐的配图（§119）：从食谱、减脂餐记的用它的图；否则用分量最大、有图的那样食物的图。"""
    from ironm_agent.food_images import image_for

    if meal.image_key and (im := image_for(meal.image_key)):
        return im
    for x in sorted(meal.foods, key=lambda f: -f.grams):
        if x.food_id and (im := image_for(f"food:{x.food_id}")):
            return im
    return None


def meal_from(kind: MealKind, name: str, lines: Sequence[FoodLine], **extra: Any) -> Meal:
    """按逐样食物拼一条记录：整餐营养是各样加起来。"""
    note = extra.pop("note", "")
    if any(x.est100 is not None for x in lines):
        guess = "、".join(x.name for x in lines if x.est100 is not None)
        note = "；".join(s for s in (note, f"库里没有，按估算：{guess}") if s)
    return Meal(kind=kind, name=name[:40] or "这一餐", items=[line_text(x) for x in lines],
                macros=sum_lines(lines), foods=list(lines), note=note[:120], **extra)  # fmt: skip


# ---- 估算 -----------------------------------------------------------------------------------

_ESTIMATE = """你是健身 App 里的营养师，根据用户拍的照片和描述，说出这一餐有哪些食物、各多少。

做法：
1. 认出每一样食物，写常见的叫法（米饭、番茄炒蛋、鸡胸肉），估吃下去的克数；描述里说的量（比如"吃了一半"）优先于照片。
2. 炒菜、外卖菜写油量：少油、正常、多油；看不出就写正常。不用你算热量，系统按食物库算。
3. 每样再给一个每 100 克的营养估值（per100），库里查不到时才用。
4. 拿不准的地方写进 note，比如"看不出用了多少油"；照片里不是食物或看不清时，confidence 写"低"并在 note 里说明。

只输出 JSON：{"name": "这一餐的简短名字", "foods": [{"name": "米饭", "grams": 150, "oil": "正常", "per100": {"kcal": 130, "protein_g": 2.7, "carbs_g": 28, "fat_g": 0.3}}], "confidence": "低/中/高", "note": "拿不准的地方"}"""


async def estimate(
    llm: LLM, said: str, kind: MealKind, image: Mapping[str, Any] | None = None
) -> Meal | None:
    """照片加描述 → 一条估算的记录；模型不可用或输出不合格时返回 None。"""
    text = f"这一餐：{kind}。用户的描述：{said or '（没写描述，只看照片）'}"
    content: str | list[Any] = [{"type": "text", "text": text}, image] if image else text
    try:
        reply = await llm.chat(
            "expert",
            [{"role": "system", "content": _ESTIMATE}, {"role": "user", "content": content}],
            json_mode=True,
        )
    except ModelUnavailable:
        return None
    raw = parse_json(reply.content) or {}
    lines = _lines(raw.get("foods"))
    if lines:  # 模型只认食物和分量，营养由食物库算（§118）
        return meal_from(kind, str(raw.get("name") or said or "这一餐"), lines,
                         confidence=str(raw.get("confidence") or "")[:4],
                         note=str(raw.get("note") or ""), said=said[:120])  # fmt: skip
    try:  # 没给逐样食物时照旧用它估的整餐营养
        macros, changed = Macros.model_validate(raw).reconciled()
        note = str(raw.get("note") or "")
        if changed:
            note = (note + "；" if note else "") + "热量按营养素重新算过"
        return Meal(
            kind=kind,
            name=str(raw.get("name") or said or "这一餐")[:40],
            items=[str(x)[:40] for x in (raw.get("items") or [])][:12],
            macros=macros.rounded(),
            confidence=str(raw.get("confidence") or "")[:4],
            note=note[:120],
            said=said[:120],
        )
    except ValidationError:
        return None


def _lines(raw: Any) -> list[FoodLine]:
    """模型给的逐样食物 → 按库算好的；克数不合理、库里没有又没给估值的跳过。"""
    out: list[FoodLine] = []
    for x in raw if isinstance(raw, list) else []:
        if not isinstance(x, dict) or not str(x.get("name") or "").strip():
            continue
        try:
            grams = float(x.get("grams") or 0)
            est = (
                Macros.model_validate(x["per100"]).reconciled()[0]
                if isinstance(x.get("per100"), dict)
                else None
            )
            if 0 < grams <= 3000:
                out.append(
                    food_line(str(x["name"]), grams, str(x.get("oil") or "正常"), est100=est)
                )
        except (KeyError, ValueError, ValidationError):
            continue
    return out[:12]


# ---- 推荐 -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class DayContext:
    """推荐一餐时要考虑的情况（都已经是给人看的短句，不含原始健康数据）。"""

    kind: MealKind
    appetite: Appetite
    goal: str = ""  # 目标
    target: Macros | None = None  # 今日目标
    eaten: Macros | None = None  # 今天已经吃的
    weather: str = ""  # 天气与对训练的影响
    state: str = ""  # 今天的身体数据（数值和与他平时的差，不定级，§182）
    limits: tuple[str, ...] = ()  # 饮食限制与喜好（来自记忆）
    trained_today: bool = False

    def remaining(self) -> Macros | None:
        if self.target is None:
            return None
        e = self.eaten or Macros(kcal=0, protein_g=0, carbs_g=0, fat_g=0)
        return Macros(
            kcal=max(0.0, self.target.kcal - e.kcal),
            protein_g=max(0.0, self.target.protein_g - e.protein_g),
            carbs_g=0,
            fat_g=0,
        )

    def text(self) -> str:
        lines = [f"这一餐：{self.kind}；胃口：{self.appetite}"]
        if self.goal:
            lines.append(f"目标：{self.goal}")
        rest = self.remaining()
        if self.target is not None and rest is not None:
            lines.append(
                f"今日目标：热量约 {self.target.kcal:.0f} 千卡、蛋白质 {self.target.protein_g:.0f} 克；"
                f"今天还剩：热量约 {rest.kcal:.0f} 千卡、蛋白质约 {rest.protein_g:.0f} 克"
            )
        if self.state:
            lines.append(self.state)
        if self.weather:
            lines.append(self.weather)
        if self.trained_today:
            lines.append("今天已经练过")
        if self.limits:
            lines.append("饮食限制与喜好（一定要照顾）：" + "；".join(self.limits))
        return "\n".join(lines)


class Dish(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=30)
    amount: str = Field(default="", max_length=30)
    kcal: float = Field(ge=0, le=3000)
    protein_g: float = Field(ge=0, le=300)
    carbs_g: float = Field(ge=0, le=500)
    fat_g: float = Field(ge=0, le=300)


class Recommendation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=1, max_length=30)
    why: str = Field(default="", max_length=200)
    dishes: list[Dish] = Field(min_length=1, max_length=8)
    tips: str = Field(default="", max_length=120)

    def total(self) -> Macros:
        return Macros(
            kcal=round(sum(d.kcal for d in self.dishes)),
            protein_g=round(sum(d.protein_g for d in self.dishes)),
            carbs_g=round(sum(d.carbs_g for d in self.dishes)),
            fat_g=round(sum(d.fat_g for d in self.dishes)),
        )


_RECOMMEND = """你是健身 App 里的营养师，给用户推荐这一餐吃什么。

要求：
1. 先满足目标：今天还缺的蛋白质尽量在这一餐补上一部分；热量不要超出今天剩下的额度。
2. 按胃口调整：想吃清淡就少油少辣、汤和蒸煮为主；很饿就选饱腹感强的（蛋白质、蔬菜、粗粮多一些），总热量仍然在额度内。
3. 按天气调整：天热选清爽、补水多的，天冷选热乎的；睡眠、心率比他平时差得多，或者他说累、不舒服时选好消化的。
4. 一定照顾饮食限制与喜好（比如乳糖不耐就不用牛奶）。
5. 推荐在中国常见、容易买到或做的饭菜，一个人一餐 2–4 样就够；每道写清分量，并估算热量、蛋白质、碳水、脂肪（蛋白质 × 4 + 碳水 × 4 + 脂肪 × 9 ≈ 热量）。
6. why 用一两句话说明为什么这样推荐（提到目标、胃口、天气或状态里起作用的那几条）。

只输出 JSON：{"title": "推荐的名字", "why": "为什么", "dishes": [{"name": "", "amount": "", "kcal": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0}], "tips": "一句吃法上的提醒"}"""


_LIMITS = {"title": 30, "why": 200, "tips": 120, "name": 30, "amount": 30}


def _clip(raw: Any) -> Any:
    """模型写的推荐常常某段字多一点、菜多一两道：截短，而不是整份作废。"""
    if isinstance(raw, dict):
        out = {}
        for k, v in raw.items():
            if isinstance(v, str) and k in _LIMITS:
                v = v.strip()[: _LIMITS[k]]
            elif k == "dishes" and isinstance(v, list):
                v = v[:8]
            out[k] = _clip(v)
        return out
    if isinstance(raw, list):
        return [_clip(x) for x in raw]
    return raw


def over_budget(rec: Recommendation, ctx: DayContext) -> str:
    """推荐超出今天剩余热量太多时返回原因，否则为空。"""
    rest = ctx.remaining()
    if rest is None:
        return ""
    total = rec.total().kcal
    if total > rest.kcal * OVER_REMAINING and total - rest.kcal > 100:
        return f"这一餐约 {total:.0f} 千卡，超出了今天剩下的约 {rest.kcal:.0f} 千卡"
    return ""


async def recommend(llm: LLM, ctx: DayContext) -> tuple[Recommendation | None, str]:
    """推荐一餐：不合格或超额时带着原因重写一次；返回推荐与没能解决的问题。"""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _RECOMMEND},
        {"role": "user", "content": ctx.text()},
    ]
    problem = ""
    last: Recommendation | None = None
    for _ in range(2):
        try:
            reply = await llm.chat("expert", messages, json_mode=True)
        except ModelUnavailable:
            return None, "这次没能调用模型"
        raw = _clip(parse_json(reply.content) or {})
        try:
            last = Recommendation.model_validate(raw)
        except ValidationError:
            problem = "输出不是规定的格式"
        else:
            problem = over_budget(last, ctx)
            if not problem:
                return last, ""
        messages += [
            {"role": "assistant", "content": reply.content},
            {"role": "user", "content": f"这份推荐不合格（{problem}），请改好后只输出 JSON。"},
        ]
    return last, problem  # 改了一次仍超额：照样给出，并说明超出了多少


# ---- 减脂餐 ---------------------------------------------------------------------------------


class Preset(ContractModel):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    name: str
    scene: Literal["外卖", "食堂", "便利店", "自己做"]
    items: tuple[str, ...] = Field(min_length=1)
    kcal: int
    protein_g: int
    carbs_g: int
    fat_g: int
    tip: str = ""


class PresetFile(ContractModel):
    version: str
    review: str
    presets: tuple[Preset, ...]


@cache
def presets(path: Path = PRESETS_PATH) -> tuple[Preset, ...]:
    out = PresetFile.model_validate(load_yaml(path), strict=False).presets
    ids = [x.id for x in out]
    if len(ids) != len(set(ids)):
        raise ValueError("减脂餐编号重复")
    for x in out:  # 热量要和营养素对得上
        calc = x.protein_g * 4 + x.carbs_g * 4 + x.fat_g * 9
        if abs(x.kcal - calc) > KCAL_TOLERANCE * calc:
            raise ValueError(f"减脂餐 {x.id} 的热量和营养素对不上")
    return out


def preset_meal(p: Preset, kind: MealKind) -> Meal:
    return Meal(
        kind=kind,
        name=p.name,
        items=list(p.items),
        macros=Macros(kcal=p.kcal, protein_g=p.protein_g, carbs_g=p.carbs_g, fat_g=p.fat_g),
        note="按常见分量估算",
        image_key=f"preset:{p.id}",
    )


# ---- 存储 -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class StoredMeal:
    id: str
    day: date
    meal: Meal
    created: datetime
    has_photo: bool = False

    def json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "day": self.day.isoformat(),
            "created": self.created.isoformat(),
            "has_photo": self.has_photo,
            **self.meal.model_dump(mode="json"),
            "image": meal_image(self.meal),
        }


class MealStore(Protocol):
    async def add(
        self, user_id: str, day: date, meal: Meal, photo: bytes | None = None, mime: str = ""
    ) -> StoredMeal: ...
    async def day(self, user_id: str, day: date) -> list[StoredMeal]: ...
    async def since(self, user_id: str, day: date) -> list[StoredMeal]: ...
    async def replace(self, user_id: str, meal_id: str, meal: Meal) -> StoredMeal | None: ...
    async def photo(self, user_id: str, meal_id: str) -> tuple[bytes, str] | None: ...
    async def delete(self, user_id: str, meal_id: str) -> bool: ...


def totals(meals: Sequence[StoredMeal]) -> Macros:
    return Macros(
        kcal=round(sum(m.meal.macros.kcal for m in meals)),
        protein_g=round(sum(m.meal.macros.protein_g for m in meals)),
        carbs_g=round(sum(m.meal.macros.carbs_g for m in meals)),
        fat_g=round(sum(m.meal.macros.fat_g for m in meals)),
    )


def day_bill(meals: Sequence[StoredMeal], kcal: float | None, protein: float | None) -> str:
    """今天的饮食账单一行（§187，和首页饮食账单同一份）：各餐、合计、目标、还能吃多少。"""
    order = {k: i for i, k in enumerate(MEAL_KINDS)}
    got = totals(meals)
    if meals:
        each = "、".join(f"{m.meal.kind}{m.meal.name}约 {round(m.meal.macros.kcal)} 千卡"
                         for m in sorted(meals, key=lambda m: (order.get(m.meal.kind, 99), m.created)))  # fmt: skip
        parts = [f"已记 {len(meals)} 餐：{each}",
                 f"合计约 {round(got.kcal)} 千卡、蛋白质 {round(got.protein_g)} 克"]  # fmt: skip
    else:
        parts = ["今天还没记饮食"]
    if kcal:
        left = max(0, round(kcal - got.kcal))
        parts.append(f"热量目标约 {round(kcal)} 千卡，还能吃约 {left} 千卡")
    if protein:
        short = max(0, round(protein - got.protein_g))
        parts.append(f"蛋白质目标约 {round(protein)} 克，还差约 {short} 克")
    return "；".join(parts)


class MealBook:
    """内存版（测试与考题用）。"""

    def __init__(self) -> None:
        self.rows: dict[str, tuple[str, StoredMeal, bytes | None, str]] = {}

    async def add(
        self, user_id: str, day: date, meal: Meal, photo: bytes | None = None, mime: str = ""
    ) -> StoredMeal:
        row = StoredMeal(
            uuid.uuid4().hex, day, meal, datetime.now().astimezone(), photo is not None
        )
        self.rows[row.id] = (user_id, row, photo, mime)
        return row

    async def day(self, user_id: str, day: date) -> list[StoredMeal]:
        return sorted(
            (r for u, r, _, _ in self.rows.values() if u == user_id and r.day == day),
            key=lambda r: r.created,
        )

    async def since(self, user_id: str, day: date) -> list[StoredMeal]:
        return sorted(
            (r for u, r, _, _ in self.rows.values() if u == user_id and r.day >= day),
            key=lambda r: (r.day, r.created),
        )

    async def replace(self, user_id: str, meal_id: str, meal: Meal) -> StoredMeal | None:
        found = self.rows.get(meal_id)
        if found is None or found[0] != user_id:
            return None
        row = StoredMeal(found[1].id, found[1].day, meal, found[1].created, found[1].has_photo)
        self.rows[meal_id] = (user_id, row, found[2], found[3])
        return row

    async def photo(self, user_id: str, meal_id: str) -> tuple[bytes, str] | None:
        found = self.rows.get(meal_id)
        if found is None or found[0] != user_id or found[2] is None:
            return None
        return found[2], found[3]

    async def delete(self, user_id: str, meal_id: str) -> bool:
        found = self.rows.get(meal_id)
        if found is None or found[0] != user_id:
            return False
        del self.rows[meal_id]
        return True


DDL = """
CREATE TABLE IF NOT EXISTS ironm_meal (
    id         text PRIMARY KEY,
    user_id    text NOT NULL,
    day        date NOT NULL,
    content    text NOT NULL,
    photo      text,
    photo_mime text,
    created_at timestamptz NOT NULL DEFAULT now()
)
"""
INDEX = "CREATE INDEX IF NOT EXISTS ironm_meal_user_day ON ironm_meal (user_id, day)"


class PgMeals:
    """数据库版：记录内容和照片（base64）都用 mirobody 的加密函数加密。"""

    def __init__(self) -> None:
        self._ready = False

    async def _q(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        from mirobody.utils.db import execute_query

        if not self._ready:
            await run_ddl(DDL, INDEX)
            self._ready = True
        rows = await execute_query(sql, params or {}, log_sql=False)
        return rows if isinstance(rows, list) else []

    async def add(
        self, user_id: str, day: date, meal: Meal, photo: bytes | None = None, mime: str = ""
    ) -> StoredMeal:
        row = StoredMeal(
            uuid.uuid4().hex, day, meal, datetime.now().astimezone(), photo is not None
        )
        await self._q(
            "INSERT INTO ironm_meal (id, user_id, day, content, photo, photo_mime, created_at) VALUES "
            "(:id, :uid, :day, encrypt_content(:content), "
            "CASE WHEN CAST(:photo AS text) IS NULL THEN NULL ELSE encrypt_content(:photo) END, :mime, :created)",
            {
                "id": row.id,
                "uid": user_id,
                "day": day,
                "content": json.dumps(meal.model_dump(mode="json"), ensure_ascii=False),
                "photo": base64.b64encode(photo).decode() if photo else None,
                "mime": mime or None,
                "created": row.created,
            },
        )
        return row

    async def day(self, user_id: str, day: date) -> list[StoredMeal]:
        rows = await self._q(
            "SELECT id, day, decrypt_content(content) AS content, photo IS NOT NULL AS has_photo, created_at "
            "FROM ironm_meal WHERE user_id = :uid AND day = :day ORDER BY created_at",
            {"uid": user_id, "day": day},
        )
        return self._rows(rows)

    async def since(self, user_id: str, day: date) -> list[StoredMeal]:
        rows = await self._q(
            "SELECT id, day, decrypt_content(content) AS content, photo IS NOT NULL AS has_photo, created_at "
            "FROM ironm_meal WHERE user_id = :uid AND day >= :day ORDER BY day, created_at",
            {"uid": user_id, "day": day},
        )
        return self._rows(rows)

    async def replace(self, user_id: str, meal_id: str, meal: Meal) -> StoredMeal | None:
        rows = await self._q(
            "UPDATE ironm_meal SET content = encrypt_content(:content) WHERE user_id = :uid AND id = :id "
            "RETURNING id, day, photo IS NOT NULL AS has_photo, created_at",
            {"uid": user_id, "id": meal_id,
             "content": json.dumps(meal.model_dump(mode="json"), ensure_ascii=False)},
        )  # fmt: skip
        if not rows:
            return None
        r = rows[0]
        return StoredMeal(str(r["id"]), r["day"], meal, r["created_at"], bool(r["has_photo"]))

    @staticmethod
    def _rows(rows: list[dict[str, Any]]) -> list[StoredMeal]:
        out = []
        for r in rows:
            try:
                meal = Meal.model_validate(json.loads(r["content"]))
            except (ValidationError, json.JSONDecodeError, TypeError):
                continue
            out.append(
                StoredMeal(str(r["id"]), r["day"], meal, r["created_at"], bool(r["has_photo"]))
            )
        return out

    async def photo(self, user_id: str, meal_id: str) -> tuple[bytes, str] | None:
        rows = await self._q(
            "SELECT decrypt_content(photo) AS photo, photo_mime FROM ironm_meal "
            "WHERE user_id = :uid AND id = :id AND photo IS NOT NULL",
            {"uid": user_id, "id": meal_id},
        )
        if not rows or not rows[0].get("photo"):
            return None
        return base64.b64decode(rows[0]["photo"]), str(rows[0].get("photo_mime") or "image/jpeg")

    async def delete(self, user_id: str, meal_id: str) -> bool:
        rows = await self._q(
            "DELETE FROM ironm_meal WHERE user_id = :uid AND id = :id RETURNING id",
            {"uid": user_id, "id": meal_id},
        )
        return bool(rows)


_default: MealStore | None = None


def default_meals() -> MealStore:
    global _default
    if _default is None:
        _default = PgMeals()
    return _default
