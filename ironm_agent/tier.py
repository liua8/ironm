"""夯：个人的从夯到拉榜单（spec [2026-10-23] §60）。

类别：动作按部位（条目是动作库里这个部位的动作）、补剂和蛋白粉、食物（条目自己添加）。五档从上到下是
夯、顶级、人上人、NPC、拉；没排的算"还没排"。每人每个条目一行；数据库版的条目内容用 mirobody 的加密函数
加密，行的编号由人、类别、条目算出来（不含原文）；日志不写内容。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from ironm_agent.exercises import library

TIERS: tuple[tuple[str, str], ...] = (
    ("hang", "夯"), ("top", "顶级"), ("elite", "人上人"), ("npc", "NPC"), ("la", "拉"),
)  # fmt: skip
TIER_KEYS = frozenset(k for k, _ in TIERS)
MOVE_PARTS: tuple[str, ...] = ("胸", "背", "肩", "手臂", "核心", "腿臀")
CUSTOM = ("supplement", "food")  # 条目自己添加的类别
CATEGORY_NAMES: dict[str, str] = {
    **{f"move:{p}": f"{p}的动作" for p in MOVE_PARTS},
    "supplement": "补剂和蛋白粉",
    "food": "食物",
}
NAME_MAX = 30

type Tier = Literal["hang", "top", "elite", "npc", "la"]


class TierError(ValueError):
    """用户可以看懂的错误（接口返回 422）。"""


@dataclass(frozen=True)
class Row:
    category: str
    key: str  # 动作是动作编号；自己添加的是 c: 加名字
    name: str
    tier: str  # 空串是"还没排"


def check_category(category: str) -> None:
    if category not in CATEGORY_NAMES:
        raise TierError("没有这个类别")


def clean_name(name: str) -> str:
    text = " ".join(str(name).split())
    if not text:
        raise TierError("名字不能为空")
    if len(text) > NAME_MAX:
        raise TierError(f"名字最多 {NAME_MAX} 个字")
    return text


def custom_key(name: str) -> str:
    return "c:" + clean_name(name).casefold()


def moves_of(part: str) -> list[tuple[str, str]]:
    """这个部位在动作库里的动作：(编号, 名字)。"""
    return [(x.id, x.name) for x in library().exercises if x.part == part]


def row_id(user_id: str, category: str, key: str) -> str:
    return hashlib.sha256(f"{user_id}\x1f{category}\x1f{key}".encode()).hexdigest()[:32]


class TierStore(Protocol):
    async def rows(self, user_id: str, category: str) -> list[Row]: ...
    async def put(self, user_id: str, row: Row) -> None: ...
    async def delete(self, user_id: str, category: str, key: str) -> bool: ...


class TierBook:
    """内存版（测试用）。"""

    def __init__(self) -> None:
        self.data: dict[str, dict[str, Row]] = {}

    async def rows(self, user_id: str, category: str) -> list[Row]:
        return [r for r in self.data.get(user_id, {}).values() if r.category == category]

    async def put(self, user_id: str, row: Row) -> None:
        self.data.setdefault(user_id, {})[row_id(user_id, row.category, row.key)] = row

    async def delete(self, user_id: str, category: str, key: str) -> bool:
        return self.data.get(user_id, {}).pop(row_id(user_id, category, key), None) is not None


DDL = """
CREATE TABLE IF NOT EXISTS ironm_tier (
    id         text PRIMARY KEY,
    user_id    text NOT NULL,
    category   text NOT NULL,
    tier       text NOT NULL DEFAULT '',
    content    text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ironm_tier_user ON ironm_tier (user_id, category)
"""


class PgTier:
    """数据库版：条目的编号和名字加密后存；类别和档位不加密（不含个人内容）。"""

    def __init__(self) -> None:
        self._ready = False

    async def _q(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        from mirobody.utils.db import execute_query

        if not self._ready:
            for stmt in DDL.split(";"):
                if stmt.strip():
                    await execute_query(stmt, {}, log_sql=False)
            self._ready = True
        rows = await execute_query(sql, params, log_sql=False)
        return rows if isinstance(rows, list) else []

    async def rows(self, user_id: str, category: str) -> list[Row]:
        got = await self._q(
            "SELECT decrypt_content(content) AS content, tier FROM ironm_tier"
            " WHERE user_id = :uid AND category = :cat ORDER BY updated_at",
            {"uid": user_id, "cat": category},
        )
        out = []
        for r in got:
            try:
                item = json.loads(str(r["content"]))
                out.append(Row(category, str(item["key"]), str(item["name"]), str(r["tier"] or "")))
            except (ValueError, KeyError, TypeError):
                continue
        return out

    async def put(self, user_id: str, row: Row) -> None:
        content = json.dumps({"key": row.key, "name": row.name}, ensure_ascii=False)
        await self._q(
            "INSERT INTO ironm_tier (id, user_id, category, tier, content)"
            " VALUES (:id, :uid, :cat, :tier, encrypt_content(:content))"
            " ON CONFLICT (id) DO UPDATE SET tier = EXCLUDED.tier, content = EXCLUDED.content, updated_at = now()",
            {"id": row_id(user_id, row.category, row.key), "uid": user_id, "cat": row.category,
             "tier": row.tier, "content": content},
        )  # fmt: skip

    async def delete(self, user_id: str, category: str, key: str) -> bool:
        got = await self._q(
            "DELETE FROM ironm_tier WHERE id = :id AND user_id = :uid RETURNING id",
            {"id": row_id(user_id, category, key), "uid": user_id},
        )
        return bool(got)


_default: TierStore | None = None


def default_tier() -> TierStore:
    global _default
    if _default is None:
        _default = PgTier()
    return _default


# ---- 读、改 ---------------------------------------------------------------------------------


async def board(store: TierStore, user_id: str, category: str) -> dict[str, Any]:
    """一个类别的榜：五档各有哪些条目，还有"还没排"的。动作类按动作库列全，自己添加的按存下的列。"""
    check_category(category)
    saved = {r.key: r for r in await store.rows(user_id, category)}
    if category.startswith("move:"):
        items = [
            (key, name, saved[key].tier if key in saved else "")
            for key, name in moves_of(category[5:])
        ]
    else:
        items = [(r.key, r.name, r.tier) for r in saved.values()]
    rows = [{"key": k, "name": n, "tier": t if t in TIER_KEYS else ""} for k, n, t in items]
    return {
        "category": category,
        "name": CATEGORY_NAMES[category],
        "custom": category in CUSTOM,
        "tiers": [{"key": k, "name": n} for k, n in TIERS],
        "items": rows,
    }


async def set_tier(store: TierStore, user_id: str, category: str, key: str, tier: str) -> None:
    """把一个条目放进某一档；tier 为空串就是移回"还没排"。"""
    check_category(category)
    if tier and tier not in TIER_KEYS:
        raise TierError("没有这一档")
    if category.startswith("move:"):
        name = dict(moves_of(category[5:])).get(key)
        if name is None:
            raise TierError("这个部位没有这个动作")
        if not tier:
            await store.delete(user_id, category, key)
            return
    else:
        found = next((r for r in await store.rows(user_id, category) if r.key == key), None)
        if found is None:
            raise TierError("没有这个条目，先添加")
        name = found.name
    await store.put(user_id, Row(category, key, name, tier))


async def add_item(store: TierStore, user_id: str, category: str, name: str) -> str:
    """自己添加一个条目（补剂、食物），先放在"还没排"；已经有了就不重复加。返回条目编号。"""
    check_category(category)
    if category not in CUSTOM:
        raise TierError("动作类的条目来自动作库，不能自己加")
    text = clean_name(name)
    key = custom_key(text)
    if not any(r.key == key for r in await store.rows(user_id, category)):
        await store.put(user_id, Row(category, key, text, ""))
    return key


async def remove_item(store: TierStore, user_id: str, category: str, key: str) -> None:
    check_category(category)
    if category not in CUSTOM:
        raise TierError("动作类的条目不能删除，可以移回还没排")
    if not await store.delete(user_id, category, key):
        raise TierError("没有这个条目")


def frequent_foods(names: list[str], have: set[str], k: int = 12) -> list[str]:
    """最近常吃的（按次数），去掉榜里已经有的。"""
    counts: dict[str, int] = {}
    for n in names:
        text = " ".join(n.split())
        if text and len(text) <= NAME_MAX and custom_key(text) not in have:
            counts[text] = counts.get(text, 0) + 1
    return [n for n, _ in sorted(counts.items(), key=lambda x: -x[1])][:k]
