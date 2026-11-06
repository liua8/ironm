"""食谱和饮食计划（spec [2026-10-23] §118 需求 5、6）。

食谱：推荐的（recipes.yaml，Claude 整理，待审定）和自建的（只属于本人、加密存）；营养都按食物库算，
每份 = 全部原料加油 ÷ 份数。按份数记成一餐时，每样原料按比例写进这一餐，不调用模型。
饮食计划：工作日、周末各一套，早餐、午餐、晚餐、加餐四个位置，每个位置放一个食谱、减脂餐或常吃的。
自建食谱和饮食计划存在同一张小表里（按种类分），内容加密；日志不记内容。
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from functools import cache
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ironm_agent.foods import OIL_ID, Per100, by_id, foods
from ironm_agent.meals import FoodLine, Macros, Meal, MealKind, food_line, meal_from
from ironm_agent.yamlfile import load_yaml

RECIPES_PATH = Path(__file__).with_name("recipes.yaml")
TAGS = ("减脂", "增肌", "早餐", "带饭", "素食")
SLOTS: tuple[MealKind, ...] = ("早餐", "午餐", "晚餐", "加餐")
type PlanSet = Literal["weekday", "weekend"]
MAX_PARTS = 11  # 加上油一共不超过一餐的 12 样


class Part(BaseModel):
    model_config = ConfigDict(extra="forbid")

    food_id: str = Field(min_length=1, max_length=40)
    grams: float = Field(gt=0, le=3000)


class Recipe(BaseModel):
    """一个食谱：推荐的和自建的同一个样子。"""

    model_config = ConfigDict(extra="forbid")

    id: str = ""
    name: str = Field(min_length=1, max_length=20)
    tags: list[str] = Field(default_factory=list, max_length=4)
    servings: int = Field(default=1, ge=1, le=10)
    parts: list[Part] = Field(min_length=1, max_length=MAX_PARTS)
    oil: float = Field(default=0, ge=0, le=200)
    steps: list[str] = Field(default_factory=list, max_length=6)
    mine: bool = False

    def whole(self) -> Per100:
        lib = by_id()
        total = lib[OIL_ID].nutrition(self.oil)
        for p in self.parts:
            total = total.plus(lib[p.food_id].nutrition(p.grams))
        return total

    def per_serving(self) -> Macros:
        n = self.whole().times(1 / self.servings)
        return Macros(
            kcal=n.kcal, protein_g=n.protein_g, carbs_g=n.carbs_g, fat_g=n.fat_g
        ).rounded()

    def lines(self, servings: float) -> list[FoodLine]:
        """吃了几份：每样原料按比例。"""
        k = servings / self.servings
        out = [food_line("", max(1, p.grams * k), food_id=p.food_id) for p in self.parts]
        if self.oil:
            out.append(food_line("", max(1, self.oil * k), food_id=OIL_ID))
        return out

    def meal(self, kind: MealKind, servings: float) -> Meal:
        name = self.name if servings == 1 else f"{self.name}（{servings:g} 份）"
        return meal_from(kind, name, self.lines(servings), estimated=False, note="按食谱和食物库算",
                         image_key="" if self.mine else f"recipe:{self.id}")  # fmt: skip

    def image(self) -> dict[str, Any] | None:
        """推荐食谱用它自己的图；自建的用分量最大、有图的那样原料的图（§119）。"""
        from ironm_agent.food_images import image_for

        if not self.mine and (im := image_for(f"recipe:{self.id}")):
            return im
        for p in sorted(self.parts, key=lambda x: -x.grams):
            if im := image_for(f"food:{p.food_id}"):
                return im
        return None

    def shown(self) -> dict[str, Any]:
        lib = by_id()
        return {
            **self.model_dump(mode="json"),
            "parts": [
                {"food_id": p.food_id, "name": lib[p.food_id].name, "grams": p.grams}
                for p in self.parts
            ],
            "per_serving": self.per_serving().model_dump(),
            "image": self.image(),
        }


def check_parts(parts: list[Part]) -> None:
    """原料都要在食物库里。"""
    lib = by_id()
    missing = [p.food_id for p in parts if p.food_id not in lib]
    if missing:
        raise ValueError(f"食物库里没有：{'、'.join(missing)}")


@cache
def recommended(path: Path = RECIPES_PATH) -> tuple[Recipe, ...]:
    raw: dict[str, Any] = load_yaml(path)  # type: ignore[assignment]
    names = {f.name: f.id for f in foods()}
    out = []
    for x in raw["recipes"]:
        parts = [
            Part(food_id=names[n], grams=float(g)) for n, g in x["parts"].items()
        ]  # 名字写错时报错
        out.append(Recipe(id=x["id"], name=x["name"], tags=list(x["tags"]), servings=int(x["servings"]),
                          parts=parts, oil=float(x.get("oil") or 0), steps=list(x["steps"])))  # fmt: skip
    if len({r.id for r in out}) != len(out):
        raise ValueError("推荐食谱编号重复")
    return tuple(out)


# ---- 饮食计划 -----------------------------------------------------------------------------------


class SlotRef(BaseModel):
    """计划里一个位置放的是什么：推荐食谱、自建食谱、减脂餐，或常吃的（存一份当时的记录）。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["recipe", "mine", "preset", "meal"]
    id: str = Field(min_length=1, max_length=60)
    servings: float = Field(default=1, ge=0.5, le=3)
    snapshot: dict[str, Any] | None = None  # 常吃的：当时那一餐（名字、逐样食物、营养）


def set_of(day: date) -> PlanSet:
    return "weekend" if day.isoweekday() >= 6 else "weekday"


# ---- 存储：自建食谱和饮食计划共用一张小表 -------------------------------------------------------------


class DietStore(Protocol):
    async def put(self, user_id: str, kind: str, key: str, data: dict[str, Any]) -> None: ...
    async def get(self, user_id: str, kind: str, key: str) -> dict[str, Any] | None: ...
    async def all(self, user_id: str, kind: str) -> list[dict[str, Any]]: ...
    async def delete(self, user_id: str, kind: str, key: str) -> bool: ...


class DietBook:
    """内存版（测试与自测用）。"""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, str], dict[str, Any]] = {}

    async def put(self, user_id: str, kind: str, key: str, data: dict[str, Any]) -> None:
        self.rows[(user_id, kind, key)] = json.loads(json.dumps(data))

    async def get(self, user_id: str, kind: str, key: str) -> dict[str, Any] | None:
        return self.rows.get((user_id, kind, key))

    async def all(self, user_id: str, kind: str) -> list[dict[str, Any]]:
        return [v for (u, k, _), v in self.rows.items() if u == user_id and k == kind]

    async def delete(self, user_id: str, kind: str, key: str) -> bool:
        return self.rows.pop((user_id, kind, key), None) is not None


DDL = """
CREATE TABLE IF NOT EXISTS ironm_diet_kv (
    user_id    text NOT NULL,
    kind       text NOT NULL,
    key        text NOT NULL,
    content    text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, kind, key)
)
"""


class PgDiet:
    """数据库版：内容用 mirobody 的加密函数加密。"""

    def __init__(self) -> None:
        self._ready = False

    async def _q(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        from mirobody.utils.db import execute_query

        if not self._ready:
            await execute_query(DDL, {}, log_sql=False)
            self._ready = True
        rows = await execute_query(sql, params, log_sql=False)
        return rows if isinstance(rows, list) else []

    async def put(self, user_id: str, kind: str, key: str, data: dict[str, Any]) -> None:
        await self._q(
            "INSERT INTO ironm_diet_kv (user_id, kind, key, content) VALUES (:uid, :kind, :key, "
            "encrypt_content(:content)) ON CONFLICT (user_id, kind, key) DO UPDATE SET "
            "content = EXCLUDED.content, updated_at = now()",
            {
                "uid": user_id,
                "kind": kind,
                "key": key,
                "content": json.dumps(data, ensure_ascii=False),
            },
        )

    async def get(self, user_id: str, kind: str, key: str) -> dict[str, Any] | None:
        rows = await self._q(
            "SELECT decrypt_content(content) AS content FROM ironm_diet_kv "
            "WHERE user_id = :uid AND kind = :kind AND key = :key",
            {"uid": user_id, "kind": kind, "key": key},
        )
        return _load(rows[0]["content"]) if rows else None

    async def all(self, user_id: str, kind: str) -> list[dict[str, Any]]:
        rows = await self._q(
            "SELECT decrypt_content(content) AS content FROM ironm_diet_kv "
            "WHERE user_id = :uid AND kind = :kind ORDER BY updated_at DESC",
            {"uid": user_id, "kind": kind},
        )
        return [d for r in rows if (d := _load(r["content"])) is not None]

    async def delete(self, user_id: str, kind: str, key: str) -> bool:
        rows = await self._q(
            "DELETE FROM ironm_diet_kv WHERE user_id = :uid AND kind = :kind AND key = :key RETURNING key",
            {"uid": user_id, "kind": kind, "key": key},
        )
        return bool(rows)


def _load(text: Any) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


_default: DietStore | None = None


def default_diet_store() -> DietStore:
    global _default
    if _default is None:
        _default = PgDiet()
    return _default


async def my_recipes(store: DietStore, user_id: str) -> list[Recipe]:
    out = []
    for d in await store.all(user_id, "recipe"):
        try:
            r = Recipe.model_validate(d)
            check_parts(r.parts)
        except (ValidationError, ValueError):
            continue  # 食物库改过、对不上的跳过
        out.append(r)
    return out


def new_id() -> str:
    return uuid.uuid4().hex[:16]
