"""Agent 记忆（L1 记忆条目）的存储：一条条带类别、状态、原话片段的记忆。

- 情况变化时不改原来那条，而是新增一条并把旧的标为"被新说法取代"，旧的不再用于回答；
- 内容与原话片段加密存储（与 mirobody 对话内容同一种加密），日志里不写记忆内容；
- 测试和考题用内存版（MemoryBook），线上用数据库版（PgMemory），两者接口一样。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, cast

_log = logging.getLogger("ironm_agent.memory_store")

type Category = Literal[
    "injury", "equipment", "schedule", "diet", "preference", "goal", "style", "event", "advice"
]
type Status = Literal["active", "pending", "resolved", "superseded"]
type Origin = Literal["said", "inferred", "advice", "edited"]

CATEGORIES: dict[Category, str] = {
    "injury": "伤病与身体状况",
    "equipment": "器械与场地",
    "schedule": "可练时间与作息",
    "diet": "饮食限制与习惯",
    "preference": "喜好与讨厌",
    "goal": "目标",
    "style": "回答风格",
    "event": "近期事件",
    "advice": "给过的关键建议",
}
STATUSES: tuple[Status, ...] = ("active", "pending", "resolved", "superseded")
ORIGINS: dict[Origin, str] = {
    "said": "你说的",
    "inferred": "系统推断",
    "advice": "给过的建议",
    "edited": "你改过的",
}


def now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid.uuid4().hex[:16]


@dataclass(frozen=True)
class Item:
    id: str
    category: Category
    content: str  # 一句简短的说法
    evidence: str  # 支撑这条记忆的原话片段（给过的建议则是回答里的片段）
    origin: Origin
    status: Status
    created: datetime
    updated: datetime
    supersedes: str | None = None  # 取代了哪一条


@dataclass(frozen=True)
class Change:
    """提取结果落到存储上的一步：新增一条，或改一条的状态。"""

    kind: Literal["insert", "status"]
    item: Item | None = None
    id: str = ""
    status: Status = "active"


class MemoryStore(Protocol):
    async def items(self, user_id: str, *, current_only: bool = True) -> list[Item]: ...
    async def apply(self, user_id: str, changes: Sequence[Change]) -> None: ...
    async def edit(self, user_id: str, item_id: str, content: str) -> Item | None: ...
    async def confirm(self, user_id: str, item_id: str) -> Item | None: ...
    async def delete(self, user_id: str, item_id: str) -> bool: ...
    async def paused(self, user_id: str) -> bool: ...
    async def set_paused(self, user_id: str, paused: bool) -> None: ...


def chain(items: Sequence[Item], item_id: str) -> set[str]:
    """一条记忆和它取代过的所有旧版本（删除时一起删，不留下同样的内容）。"""
    by_id = {x.id: x for x in items}
    out: set[str] = set()
    cur = by_id.get(item_id)
    while cur is not None and cur.id not in out:
        out.add(cur.id)
        cur = by_id.get(cur.supersedes or "")
    return out


class MemoryBook:
    """内存版：测试与考题用。"""

    def __init__(self) -> None:
        self._items: dict[str, list[Item]] = {}
        self._paused: set[str] = set()

    async def items(self, user_id: str, *, current_only: bool = True) -> list[Item]:
        rows = list(self._items.get(user_id, []))
        return [x for x in rows if x.status != "superseded"] if current_only else rows

    async def apply(self, user_id: str, changes: Sequence[Change]) -> None:
        rows = self._items.setdefault(user_id, [])
        for c in changes:
            if c.kind == "insert" and c.item is not None:
                rows.append(c.item)
            elif c.kind == "status":
                for i, x in enumerate(rows):
                    if x.id == c.id:
                        rows[i] = replace(x, status=c.status, updated=now())

    async def edit(self, user_id: str, item_id: str, content: str) -> Item | None:
        rows = self._items.get(user_id, [])
        for i, x in enumerate(rows):
            if x.id == item_id and x.status != "superseded":
                rows[i] = replace(x, content=content, origin="edited", updated=now(),
                                  status="active" if x.status == "pending" else x.status)  # fmt: skip
                return rows[i]
        return None

    async def confirm(self, user_id: str, item_id: str) -> Item | None:
        rows = self._items.get(user_id, [])
        for i, x in enumerate(rows):
            if x.id == item_id and x.status == "pending":
                rows[i] = replace(x, status="active", updated=now())
                return rows[i]
        return None

    async def delete(self, user_id: str, item_id: str) -> bool:
        rows = self._items.get(user_id, [])
        if not any(x.id == item_id and x.status != "superseded" for x in rows):
            return False
        gone = chain(rows, item_id)
        self._items[user_id] = [x for x in rows if x.id not in gone]
        return True

    async def paused(self, user_id: str) -> bool:
        return user_id in self._paused

    async def set_paused(self, user_id: str, paused: bool) -> None:
        (self._paused.add if paused else self._paused.discard)(user_id)


DDL = (
    """
CREATE TABLE IF NOT EXISTS ironm_memory (
    id         text PRIMARY KEY,
    user_id    text NOT NULL,
    category   text NOT NULL,
    content    text NOT NULL,
    evidence   text NOT NULL,
    origin     text NOT NULL,
    status     text NOT NULL,
    supersedes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
)
""",
    "CREATE INDEX IF NOT EXISTS ironm_memory_user ON ironm_memory (user_id, status)",
    """
CREATE TABLE IF NOT EXISTS ironm_memory_state (
    user_id    text PRIMARY KEY,
    paused     boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now()
)
""",
)

# content、evidence 是加密后的文字；加密失败时 encrypt_content 返回 NULL，NOT NULL 约束让这一条写不进去
_SELECT = (
    "SELECT id, category, decrypt_content(content) AS content, decrypt_content(evidence) AS evidence,"
    " origin, status, supersedes, created_at, updated_at FROM ironm_memory"
)


def _row(r: dict[str, Any]) -> Item:
    return Item(
        id=str(r["id"]),
        category=cast(Category, r["category"]),
        content=str(r.get("content") or ""),
        evidence=str(r.get("evidence") or ""),
        origin=cast(Origin, r["origin"]),
        status=cast(Status, r["status"]),
        created=r["created_at"],
        updated=r["updated_at"],
        supersedes=r.get("supersedes"),
    )


class PgMemory:
    """数据库版：与 mirobody 同一个数据库里 iron-m 自己的表，连接沿用 mirobody 的（带加密密钥）。"""

    def __init__(self) -> None:
        self._ready = False

    async def _q(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        from mirobody.utils.db import execute_query

        if not self._ready:
            for ddl in DDL:
                await execute_query(ddl, {}, log_sql=False)
            self._ready = True
        rows = await execute_query(sql, params or {}, log_sql=False)
        return rows if isinstance(rows, list) else []

    async def items(self, user_id: str, *, current_only: bool = True) -> list[Item]:
        where = " WHERE user_id = :uid" + (" AND status <> 'superseded'" if current_only else "")
        rows = await self._q(_SELECT + where + " ORDER BY created_at", {"uid": user_id})
        return [_row(r) for r in rows]

    async def apply(self, user_id: str, changes: Sequence[Change]) -> None:
        for c in changes:
            if c.kind == "insert" and c.item is not None:
                x = c.item
                await self._q(
                    "INSERT INTO ironm_memory (id, user_id, category, content, evidence, origin,"
                    " status, supersedes, created_at, updated_at) VALUES (:id, :uid, :category,"
                    " encrypt_content(:content), encrypt_content(:evidence), :origin, :status,"
                    " :supersedes, :created, :updated)",
                    {"id": x.id, "uid": user_id, "category": x.category, "content": x.content,
                     "evidence": x.evidence, "origin": x.origin, "status": x.status,
                     "supersedes": x.supersedes, "created": x.created, "updated": x.updated},
                )  # fmt: skip
            elif c.kind == "status":
                await self._q(
                    "UPDATE ironm_memory SET status = :status, updated_at = now()"
                    " WHERE id = :id AND user_id = :uid",
                    {"status": c.status, "id": c.id, "uid": user_id},
                )

    async def edit(self, user_id: str, item_id: str, content: str) -> Item | None:
        rows = await self._q(
            "UPDATE ironm_memory SET content = encrypt_content(:content), origin = 'edited',"
            " status = CASE WHEN status = 'pending' THEN 'active' ELSE status END, updated_at = now()"
            " WHERE id = :id AND user_id = :uid AND status <> 'superseded' RETURNING id",
            {"content": content, "id": item_id, "uid": user_id},
        )
        return await self._one(user_id, item_id) if rows else None

    async def confirm(self, user_id: str, item_id: str) -> Item | None:
        rows = await self._q(
            "UPDATE ironm_memory SET status = 'active', updated_at = now()"
            " WHERE id = :id AND user_id = :uid AND status = 'pending' RETURNING id",
            {"id": item_id, "uid": user_id},
        )
        return await self._one(user_id, item_id) if rows else None

    async def delete(self, user_id: str, item_id: str) -> bool:
        rows = await self.items(user_id, current_only=False)
        if not any(x.id == item_id and x.status != "superseded" for x in rows):
            return False
        await self._q(
            "DELETE FROM ironm_memory WHERE user_id = :uid AND id = ANY(:ids)",
            {"uid": user_id, "ids": sorted(chain(rows, item_id))},
        )
        return True

    async def _one(self, user_id: str, item_id: str) -> Item | None:
        rows = await self._q(_SELECT + " WHERE user_id = :uid AND id = :id",
                             {"uid": user_id, "id": item_id})  # fmt: skip
        return _row(rows[0]) if rows else None

    async def paused(self, user_id: str) -> bool:
        rows = await self._q(
            "SELECT paused FROM ironm_memory_state WHERE user_id = :uid", {"uid": user_id}
        )
        return bool(rows and rows[0].get("paused"))

    async def set_paused(self, user_id: str, paused: bool) -> None:
        await self._q(
            "INSERT INTO ironm_memory_state (user_id, paused) VALUES (:uid, :paused)"
            " ON CONFLICT (user_id) DO UPDATE SET paused = EXCLUDED.paused, updated_at = now()",
            {"uid": user_id, "paused": paused},
        )


_default: PgMemory | None = None


def default_store() -> MemoryStore:
    """线上用的记忆存储（问答和"我的记忆"页面共用一个）。"""
    global _default
    if _default is None:
        _default = PgMemory()
    return _default
