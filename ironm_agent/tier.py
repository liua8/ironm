"""夯拉榜：所有人可见、能添加、按评分排名（spec [2026-10-23] §60、§66）。

类别：动作按部位（条目是动作库里这个部位的动作）、补剂和蛋白粉、食物（任何人都能添加，条目公开）。
每人把一个条目放进哪一档就是投一票（夯 5 … 拉 1）；社区榜按平均分分档、档内按收缩分排，不到 3 票的
放"待评"。只公开每档票数和平均分，不公开谁投了什么、谁添加的；日志只写类别。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from difflib import SequenceMatcher
from typing import Any, Protocol

from ironm_agent.ddl import run_ddl
from ironm_agent.exercises import library

TIERS: tuple[tuple[str, str], ...] = (
    ("hang", "夯"), ("top", "顶级"), ("elite", "人上人"), ("npc", "NPC"), ("la", "拉"),
)  # fmt: skip
TIER_KEYS = frozenset(k for k, _ in TIERS)
POINTS = {"hang": 5, "top": 4, "elite": 3, "npc": 2, "la": 1}
CUTS = (
    (4.5, "hang"),
    (3.5, "top"),
    (2.5, "elite"),
    (1.5, "npc"),
)  # 平均分到这条线就进这一档，都不到是拉
MIN_VOTES = 3  # 不到这么多票放"待评"
PRIOR, PRIOR_WEIGHT = 3.0, 3  # 收缩分：票少的往 3 分靠
DAILY_ADDS = 10  # 每人每天最多添加几个条目
HIDE_REPORTS = 3  # 几个不同的人举报后隐藏
MOVE_PARTS: tuple[str, ...] = ("胸", "背", "肩", "手臂", "核心", "腿臀")
CUSTOM = ("supplement", "food")  # 条目由用户添加的类别
CATEGORY_NAMES: dict[str, str] = {
    **{f"move:{p}": f"{p}的动作" for p in MOVE_PARTS},
    "supplement": "补剂和蛋白粉",
    "food": "食物",
}
NAME_MAX = 30
_PUNCT = re.compile(r"[\s\-_·•.,，。、()（）\[\]【】/／+＋:：'\"“”‘’!！?？]+")


class TierError(ValueError):
    """用户可以看懂的错误（接口返回 422）。"""


@dataclass(frozen=True)
class Item:
    category: str
    key: str  # c: 加规整后的名字
    name: str
    added_by: str  # 只在服务端用（每天添加上限），不返回
    created: datetime


@dataclass(frozen=True)
class Vote:
    user_id: str  # 只在服务端用（认出"我投的"），不返回
    key: str
    tier: str


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


def norm(name: str) -> str:
    """比较用：去掉空格和标点、不分大小写。"""
    return _PUNCT.sub("", name).casefold()


def custom_key(name: str) -> str:
    key = norm(clean_name(name))
    if not key:
        raise TierError("名字里要有字")
    return "c:" + key


def moves_of(part: str) -> list[tuple[str, str]]:
    """这个部位在动作库里的动作：(编号, 名字)。"""
    return [(x.id, x.name) for x in library().exercises if x.part == part]


def similar(name: str, items: Sequence[Item], k: int = 5) -> list[Item]:
    """和已有条目相似的（包含关系或很接近），最像的在前。"""
    n = norm(name)
    scored = []
    for x in items:
        m = norm(x.name)
        r = SequenceMatcher(None, n, m).ratio()
        if n and m and (n in m or m in n or r >= 0.75):
            scored.append((r, x))
    return [x for _, x in sorted(scored, key=lambda s: -s[0])][:k]


class TierStore(Protocol):
    async def items(self, category: str) -> list[Item]: ...
    async def add(self, item: Item) -> None: ...
    async def votes(self, category: str) -> list[Vote]: ...
    async def vote(self, user_id: str, category: str, key: str, tier: str) -> None: ...
    async def report(self, user_id: str, category: str, key: str) -> None: ...
    async def reports(self, category: str) -> dict[str, int]: ...


class TierBook:
    """内存版（测试用）。"""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], Item] = {}
        self._votes: dict[tuple[str, str, str], str] = {}
        self._reports: set[tuple[str, str, str]] = set()

    async def items(self, category: str) -> list[Item]:
        return sorted(
            (x for (c, _), x in self._items.items() if c == category), key=lambda x: x.created
        )

    async def add(self, item: Item) -> None:
        self._items.setdefault((item.category, item.key), item)

    async def votes(self, category: str) -> list[Vote]:
        return [Vote(u, k, t) for (u, c, k), t in self._votes.items() if c == category]

    async def vote(self, user_id: str, category: str, key: str, tier: str) -> None:
        if tier:
            self._votes[(user_id, category, key)] = tier
        else:
            self._votes.pop((user_id, category, key), None)

    async def report(self, user_id: str, category: str, key: str) -> None:
        self._reports.add((user_id, category, key))

    async def reports(self, category: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for _, c, k in self._reports:
            if c == category:
                out[k] = out.get(k, 0) + 1
        return out


DDL = """
CREATE TABLE IF NOT EXISTS ironm_tier_item (
    category   text NOT NULL,
    key        text NOT NULL,
    name       text NOT NULL,
    added_by   text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (category, key)
);
CREATE TABLE IF NOT EXISTS ironm_tier_vote (
    user_id    text NOT NULL,
    category   text NOT NULL,
    key        text NOT NULL,
    tier       text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, category, key)
);
CREATE INDEX IF NOT EXISTS ironm_tier_vote_cat ON ironm_tier_vote (category);
CREATE TABLE IF NOT EXISTS ironm_tier_report (
    user_id    text NOT NULL,
    category   text NOT NULL,
    key        text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, category, key)
)
"""


class PgTier:
    """数据库版：条目名公开、不加密；投票只存档位（不含个人内容），接口和日志都不带投票人。"""

    def __init__(self) -> None:
        self._ready = False

    async def _q(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        from mirobody.utils.db import execute_query

        if not self._ready:
            await run_ddl(*DDL.split(";"))
            self._ready = True
        rows = await execute_query(sql, params, log_sql=False)
        return rows if isinstance(rows, list) else []

    async def items(self, category: str) -> list[Item]:
        got = await self._q(
            "SELECT key, name, added_by, created_at FROM ironm_tier_item"
            " WHERE category = :cat ORDER BY created_at",
            {"cat": category},
        )
        return [
            Item(category, str(r["key"]), str(r["name"]), str(r["added_by"]), r["created_at"])
            for r in got
        ]

    async def add(self, item: Item) -> None:
        await self._q(
            "INSERT INTO ironm_tier_item (category, key, name, added_by)"
            " VALUES (:cat, :key, :name, :uid) ON CONFLICT DO NOTHING",
            {"cat": item.category, "key": item.key, "name": item.name, "uid": item.added_by},
        )

    async def votes(self, category: str) -> list[Vote]:
        got = await self._q(
            "SELECT user_id, key, tier FROM ironm_tier_vote WHERE category = :cat",
            {"cat": category},
        )
        return [Vote(str(r["user_id"]), str(r["key"]), str(r["tier"])) for r in got]

    async def vote(self, user_id: str, category: str, key: str, tier: str) -> None:
        params = {"uid": user_id, "cat": category, "key": key, "tier": tier}
        if tier:
            await self._q(
                "INSERT INTO ironm_tier_vote (user_id, category, key, tier)"
                " VALUES (:uid, :cat, :key, :tier) ON CONFLICT (user_id, category, key)"
                " DO UPDATE SET tier = EXCLUDED.tier, updated_at = now()",
                params,
            )
        else:
            await self._q(
                "DELETE FROM ironm_tier_vote WHERE user_id = :uid AND category = :cat AND key = :key",
                params,
            )

    async def report(self, user_id: str, category: str, key: str) -> None:
        await self._q(
            "INSERT INTO ironm_tier_report (user_id, category, key) VALUES (:uid, :cat, :key)"
            " ON CONFLICT DO NOTHING",
            {"uid": user_id, "cat": category, "key": key},
        )

    async def reports(self, category: str) -> dict[str, int]:
        got = await self._q(
            "SELECT key, count(*) AS n FROM ironm_tier_report WHERE category = :cat GROUP BY key",
            {"cat": category},
        )
        return {str(r["key"]): int(r["n"]) for r in got}


_default: TierStore | None = None


def default_tier() -> TierStore:
    global _default
    if _default is None:
        _default = PgTier()
    return _default


# ---- 排名 -----------------------------------------------------------------------------------


def tier_of(mean: float) -> str:
    return next((t for line, t in CUTS if mean >= line), "la")


def shrunk(mean: float, n: int) -> float:
    return (mean * n + PRIOR * PRIOR_WEIGHT) / (n + PRIOR_WEIGHT)


async def _visible(store: TierStore, category: str) -> list[tuple[str, str]]:
    """这个类别所有人能看到的条目：(编号, 名字)。被 3 个人举报的不算。"""
    if category.startswith("move:"):
        return moves_of(category[5:])
    hidden = {k for k, n in (await store.reports(category)).items() if n >= HIDE_REPORTS}
    return [(x.key, x.name) for x in await store.items(category) if x.key not in hidden]


async def board(store: TierStore, user_id: str, category: str) -> dict[str, Any]:
    """一个类别的榜：每个条目的票数、平均分、社区档位（不到 3 票为空）、我投的档。按收缩分从高到低。"""
    check_category(category)
    items = await _visible(store, category)
    votes = await store.votes(category)
    rows: list[dict[str, Any]] = []
    for key, name in items:
        mine = [v for v in votes if v.key == key]
        counts = {t: sum(1 for v in mine if v.tier == t) for t in TIER_KEYS}
        n = sum(counts.values())
        mean = sum(POINTS[t] * c for t, c in counts.items()) / n if n else 0.0
        rows.append({
            "key": key,
            "name": name,
            "votes": n,
            "mean": round(mean, 1) if n else None,
            "score": round(shrunk(mean, n), 3) if n else None,
            "tier": tier_of(mean) if n >= MIN_VOTES else "",
            "counts": counts,
            "mine": next((v.tier for v in mine if v.user_id == user_id and v.tier in TIER_KEYS), ""),
        })  # fmt: skip
    rows.sort(key=lambda r: (-(r["score"] or 0), -r["votes"]))
    return {
        "category": category,
        "name": CATEGORY_NAMES[category],
        "custom": category in CUSTOM,
        "tiers": [{"key": k, "name": n} for k, n in TIERS],
        "min_votes": MIN_VOTES,
        "items": rows,
    }


async def set_tier(store: TierStore, user_id: str, category: str, key: str, tier: str) -> None:
    """投票：把条目放进某一档；tier 为空串就是撤回（移回"还没排"）。"""
    check_category(category)
    if tier and tier not in TIER_KEYS:
        raise TierError("没有这一档")
    if key not in dict(await _visible(store, category)):
        raise TierError("没有这个条目")
    await store.vote(user_id, category, key, tier)


async def add_item(
    store: TierStore, user_id: str, category: str, name: str, today: date, force: bool = False
) -> dict[str, Any]:
    """添加条目（补剂、食物）。同名的直接用已有的；有相似的且没确认（force）时不新建，返回相似的。"""
    check_category(category)
    if category not in CUSTOM:
        raise TierError("动作类的条目来自动作库，不能添加")
    text = clean_name(name)
    key = custom_key(text)
    existing = await store.items(category)
    if any(x.key == key for x in existing):
        if key not in dict(await _visible(store, category)):
            raise TierError("这个条目被举报后隐藏了")
        return {"key": key, "similar": []}
    near = similar(text, existing)
    if near and not force:
        return {"key": None, "similar": [{"key": x.key, "name": x.name} for x in near]}
    mine = [x for c in CUSTOM for x in await store.items(c) if x.added_by == user_id]
    if sum(1 for x in mine if x.created.date() == today) >= DAILY_ADDS:
        raise TierError(f"每天最多添加 {DAILY_ADDS} 个，明天再来")
    await store.add(Item(category, key, text, user_id, datetime.now().astimezone()))
    return {"key": key, "similar": []}


async def report_item(store: TierStore, user_id: str, category: str, key: str) -> None:
    check_category(category)
    if category not in CUSTOM:
        raise TierError("动作库里的动作不能举报")
    if key not in dict(await _visible(store, category)):
        raise TierError("没有这个条目")
    await store.report(user_id, category, key)


def frequent_foods(names: list[str], have: set[str], k: int = 12) -> list[str]:
    """最近常吃的（按次数），去掉榜里已经有的。"""
    counts: dict[str, int] = {}
    for n in names:
        text = " ".join(n.split())
        if text and len(text) <= NAME_MAX and norm(text) and custom_key(text) not in have:
            counts[text] = counts.get(text, 0) + 1
    return [n for n, _ in sorted(counts.items(), key=lambda x: -x[1])][:k]
