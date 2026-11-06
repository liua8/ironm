"""Agent 记忆（L1 记忆条目）的存储：一条条带类别、状态、原话片段的记忆。

- 情况变化时不改原来那条，而是新增一条并把旧的标为"被新说法取代"，旧的不再用于回答；
- 内容与原话片段加密存储（与 mirobody 对话内容同一种加密），日志里不写记忆内容；
- 测试和考题用内存版（MemoryBook），线上用数据库版（PgMemory），两者接口一样。
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, Protocol, cast

from ironm_agent.ddl import run_ddl

_log = logging.getLogger("ironm_agent.memory_store")

type Category = Literal[
    "injury",
    "equipment",
    "schedule",
    "diet",
    "preference",
    "goal",
    "style",
    "event",
    "advice",
    "followup",
    "level",
    "special",
]
type Status = Literal["active", "pending", "resolved", "superseded"]
type Origin = Literal["said", "inferred", "advice", "edited", "data", "system"]

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
    "followup": "待跟进",
    "level": "训练水平",
    "special": "特殊情况",  # 孕期、心脏病、糖尿病、高血压、近期手术（§148）
}
STATUSES: tuple[Status, ...] = ("active", "pending", "resolved", "superseded")
ORIGINS: dict[Origin, str] = {
    "said": "你说的",
    "inferred": "系统推断",
    "advice": "给过的建议",
    "edited": "你改过的",
    "data": "训练记录",
    "system": "系统",
}


# 只说一天的相对说法（§103）：记忆里写成日期，过几天再读不会当成那天
_RELATIVE = re.compile(
    r"今天早上|今天晚上|今天|今日|今早|今晨|今晚|昨天晚上|昨天|昨日|昨晚|前天|明天|明早|明晚|后天"
)
_SHIFT = {"今": 0, "昨": -1, "前": -2, "明": 1, "后": 2}


def absolute(text: str, day: date) -> str:
    """把"今天、昨晚、明天……"换成具体日期（day 是说这句话的那天）。"""

    def one(m: re.Match[str]) -> str:
        w = m.group(0)
        d = day + timedelta(days=_SHIFT[w[0]])
        part = (
            "早上"
            if w[-1] in "早晨" or w.endswith("早上")
            else "晚上"
            if w[-1] in "晚" or w.endswith("晚上")
            else ""
        )
        return f"{d.month}月{d.day}日{part}"

    return _RELATIVE.sub(one, text)


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
    until: date | None = None  # 近况到哪天为止（含这天；spec [2026-10-23] §68），没写的按 14 天
    data: dict[str, Any] = field(
        default_factory=dict
    )  # 伤病、特殊情况的结构化字段（§148，facts.py）
    key: str = ""  # 同一件事的键：同键只有一条生效（§148）


@dataclass(frozen=True)
class Change:
    """提取结果落到存储上的一步：新增一条，或改一条的状态。"""

    kind: Literal["insert", "status"]
    item: Item | None = None
    id: str = ""
    status: Status = "active"


class MemoryStore(Protocol):
    async def items(
        self, user_id: str, *, current_only: bool = True, recent: date | None = None
    ) -> list[Item]: ...  # recent：给今天的日期时不取归档了的历史（§157）
    async def apply(self, user_id: str, changes: Sequence[Change]) -> None: ...
    async def edit(self, user_id: str, item_id: str, content: str) -> Item | None: ...
    async def confirm(self, user_id: str, item_id: str) -> Item | None: ...
    async def delete(self, user_id: str, item_id: str) -> bool: ...
    async def set_fields(
        self, user_id: str, item_id: str, category: Category, data: dict[str, Any], key: str
    ) -> bool: ...
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

    async def items(
        self, user_id: str, *, current_only: bool = True, recent: date | None = None
    ) -> list[Item]:
        from ironm_agent.memory_view import archived

        rows = self._items.get(user_id, [])
        for i, x in enumerate(rows):  # 读到还没补字段的伤病、特殊情况：当场补上（§148 迁移）
            if (got := _filled(x)) is not None:
                rows[i] = got
        rows = [x for x in rows if recent is None or not archived(x, recent)]
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
                cat, data, key = _fields(x.category, content)
                rows[i] = replace(x, content=content, origin="edited", updated=now(), category=cat,
                                  data=data, key=key,
                                  status="active" if x.status == "pending" else x.status)  # fmt: skip
                return rows[i]
        return None

    async def set_fields(
        self, user_id: str, item_id: str, category: Category, data: dict[str, Any], key: str
    ) -> bool:
        rows = self._items.get(user_id, [])
        for i, x in enumerate(rows):
            if x.id == item_id:
                rows[i] = replace(x, category=category, data=dict(data), key=key)
                return True
        return False

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
    "ALTER TABLE ironm_memory ADD COLUMN IF NOT EXISTS until date",
    "ALTER TABLE ironm_memory ADD COLUMN IF NOT EXISTS data text",  # 结构化字段，加密（§148）
    "ALTER TABLE ironm_memory ADD COLUMN IF NOT EXISTS key text",
    """
CREATE TABLE IF NOT EXISTS ironm_memory_state (
    user_id    text PRIMARY KEY,
    paused     boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now()
)
""",
)

# content、evidence 是加密后的文字；加密失败时 encrypt_content 返回 NULL，NOT NULL 约束让这一条写不进去
ARCHIVED = (
    " AND NOT ((status = 'superseded' AND updated_at < :cut)"
    " OR (status = 'resolved' AND category NOT IN ('injury', 'special') AND updated_at < :cut)"
    " OR (category IN ('event', 'followup') AND ((until IS NOT NULL AND until < :cut_day)"
    " OR (until IS NULL AND created_at < :cut_events)))"
    " OR (category = 'advice' AND created_at < :cut)"
    " OR (origin = 'data' AND updated_at < :cut))"
)
_SELECT = (
    "SELECT id, category, decrypt_content(content) AS content, decrypt_content(evidence) AS evidence,"
    " origin, status, supersedes, until, created_at, updated_at,"
    " CASE WHEN data IS NULL THEN NULL ELSE decrypt_content(data) END AS data, key FROM ironm_memory"
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
        until=r.get("until"),
        data=_data(r.get("data")),
        key=str(r.get("key") or ""),
    )


def _data(raw: Any) -> dict[str, Any]:
    try:
        got = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def _fields(category: Category, content: str) -> tuple[Category, dict[str, Any], str]:
    """伤病、特殊情况按内容补字段（改了内容、迁移时用；§148）。"""
    from ironm_agent.facts import derive, key_of

    cat, data = derive(category, content)
    return cast(Category, cat), data, key_of(cat, data)


def _filled(x: Item) -> Item | None:
    """还没补字段的伤病、特殊情况、器械、可练时间（§148、§150 之前记的）：按内容补上；补不出返回 None。
    系统从训练记录推出的作息（"通常在周一、周三练"）不带键：两条推出来的不互相顶掉（复核 11-03）。"""
    from ironm_agent.facts import STRUCTURED

    if x.category not in STRUCTURED or x.data or x.status == "superseded":
        return None
    cat, data, key = _fields(x.category, x.content)
    if x.origin == "data":
        key = ""
    return replace(x, category=cat, data=data, key=key) if data else None


def _dumps(data: dict[str, Any]) -> str | None:
    return json.dumps(data, ensure_ascii=False) if data else None


class PgMemory:
    """数据库版：与 mirobody 同一个数据库里 iron-m 自己的表，连接沿用 mirobody 的（带加密密钥）。"""

    def __init__(self) -> None:
        self._ready = False

    async def _q(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        from mirobody.utils.db import execute_query

        if not self._ready:
            await run_ddl(*DDL)
            self._ready = True
        rows = await execute_query(sql, params or {}, log_sql=False)
        return rows if isinstance(rows, list) else []

    async def items(
        self, user_id: str, *, current_only: bool = True, recent: date | None = None
    ) -> list[Item]:
        where = " WHERE user_id = :uid" + (" AND status <> 'superseded'" if current_only else "")
        params: dict[str, Any] = {"uid": user_id}
        if recent is not None:  # 不取归档了的历史（§157，和 memory_view.archived 同一个口径）
            from ironm_agent.memory_view import ARCHIVE_DAYS, _midnight

            where += ARCHIVED
            params |= {"cut": _midnight(recent - timedelta(days=ARCHIVE_DAYS)),
                       "cut_day": recent - timedelta(days=ARCHIVE_DAYS),
                       "cut_events": _midnight(recent - timedelta(days=ARCHIVE_DAYS + 7))}  # fmt: skip
        rows = await self._q(_SELECT + where + " ORDER BY created_at", params)
        out = [_row(r) for r in rows]
        for i, x in enumerate(out):  # 读到还没补字段的伤病、特殊情况：当场补上写回（§148 迁移）
            if (got := _filled(x)) is not None:
                out[i] = got
                try:
                    await self.set_fields(user_id, x.id, got.category, got.data, got.key)
                except Exception as e:  # 写不回不影响这次读，下次再补
                    _log.warning("memory fields backfill failed: error_type=%s", type(e).__name__)
        return out

    async def apply(self, user_id: str, changes: Sequence[Change]) -> None:
        for c in changes:
            if c.kind == "insert" and c.item is not None:
                x = c.item
                await self._q(
                    "INSERT INTO ironm_memory (id, user_id, category, content, evidence, origin,"
                    " status, supersedes, until, created_at, updated_at, data, key) VALUES (:id, :uid,"
                    " :category, encrypt_content(:content), encrypt_content(:evidence), :origin, :status,"
                    " :supersedes, :until, :created, :updated,"
                    " CASE WHEN CAST(:data AS text) IS NULL THEN NULL ELSE encrypt_content(:data) END, :key)",
                    {"id": x.id, "uid": user_id, "category": x.category, "content": x.content,
                     "evidence": x.evidence, "origin": x.origin, "status": x.status,
                     "supersedes": x.supersedes, "until": x.until, "created": x.created, "updated": x.updated,
                     "data": _dumps(x.data), "key": x.key or None},
                )  # fmt: skip
            elif c.kind == "status":
                await self._q(
                    "UPDATE ironm_memory SET status = :status, updated_at = now()"
                    " WHERE id = :id AND user_id = :uid",
                    {"status": c.status, "id": c.id, "uid": user_id},
                )

    async def edit(self, user_id: str, item_id: str, content: str) -> Item | None:
        from ironm_agent.facts import STRUCTURED

        rows = await self._q(
            "UPDATE ironm_memory SET content = encrypt_content(:content), origin = 'edited',"
            " status = CASE WHEN status = 'pending' THEN 'active' ELSE status END, updated_at = now()"
            " WHERE id = :id AND user_id = :uid AND status <> 'superseded' RETURNING id",
            {"content": content, "id": item_id, "uid": user_id},
        )
        if not rows:
            return None
        got = await self._one(user_id, item_id)
        if got is not None and got.category in STRUCTURED:  # 改了内容：字段跟着补（§148、§150）
            cat, data, key = _fields(got.category, content)
            await self.set_fields(user_id, item_id, cat, data, key)
            got = await self._one(user_id, item_id)
        return got

    async def confirm(self, user_id: str, item_id: str) -> Item | None:
        rows = await self._q(
            "UPDATE ironm_memory SET status = 'active', updated_at = now()"
            " WHERE id = :id AND user_id = :uid AND status = 'pending' RETURNING id",
            {"id": item_id, "uid": user_id},
        )
        return await self._one(user_id, item_id) if rows else None

    async def set_fields(
        self, user_id: str, item_id: str, category: Category, data: dict[str, Any], key: str
    ) -> bool:
        """只改类别和结构化字段（迁移、改了内容后补字段；§148），不动内容、原话和历史。"""
        rows = await self._q(
            "UPDATE ironm_memory SET category = :category,"
            " data = CASE WHEN CAST(:data AS text) IS NULL THEN NULL ELSE encrypt_content(:data) END,"
            " key = :key WHERE id = :id AND user_id = :uid RETURNING id",
            {"category": category, "data": _dumps(data), "key": key or None, "id": item_id, "uid": user_id},
        )  # fmt: skip
        return bool(rows)

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
    """线上用的记忆存储（问答和记忆接口共用一个）。"""
    global _default
    if _default is None:
        _default = PgMemory()
    return _default
