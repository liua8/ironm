"""夯榜：排行榜（spec [2026-10-23] §72，取代 §66 的五档页面；§80 改版）。

六个榜：动作（动作库里的动作 + 用户加的）、训练计划（方案库）、健身餐（§80 由减脂餐、增肌餐合并）、补剂、
蛋白粉、器材，条目是通用的东西，每条带一句说明和配图（有的话）。
每人每个条目一票（夯 5 … 拉 1，照 §66），满 3 票上榜，按收缩分排名，档位作为标签。
每个条目可以评论（只显示昵称）、点赞、举报；首页有热搜（只按次数汇总，不记谁搜的）；
每周第一次有人看榜时记一次名次，用来算本周的名次变化。
§66 的投票照用：动作按部位分开的票并进动作榜，补剂和蛋白粉类就是补剂榜；食物类不显示、不删。
"""

from __future__ import annotations

import json
import re
import secrets
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any, Protocol

import yaml

from ironm_agent.ddl import run_ddl
from ironm_agent.exercise_images import images_for
from ironm_agent.exercises import library
from ironm_agent.rank_images import image_for
from ironm_agent.tier import (
    DAILY_ADDS,
    HIDE_REPORTS,
    MIN_VOTES,
    MOVE_PARTS,
    POINTS,
    TIER_KEYS,
    TIERS,
    Item,
    TierError,
    TierStore,
    Vote,
    clean_name,
    custom_key,
    norm,
    shrunk,
    similar,
    tier_of,
)

BOARDS: tuple[tuple[str, str, str], ...] = (
    ("move", "动作榜", "🏋️"), ("plan", "训练计划榜", "📋"), ("meal", "健身餐榜", "🍱"),
    ("supplement", "补剂榜", "💊"), ("protein", "蛋白粉榜", "🥛"), ("gear", "器材榜", "🧰"),
)  # fmt: skip
# 合并进来的旧榜（§80）：它们的条目、票、举报、评论都算在新榜上；新榜上投的优先
MERGED: dict[str, tuple[str, ...]] = {"meal": ("fat", "gain")}
NO_ADD = frozenset({"plan"})  # 训练计划榜的条目只来自方案库
BOARD_NAMES = {b: n for b, n, _ in BOARDS}
BOARD_ICONS = {b: i for b, _, i in BOARDS}
NO_CLAIMS = frozenset({"supplement", "protein"})  # 评论不写疗效，页面写明不代表平台观点
LEGACY_MOVES = tuple(f"move:{p}" for p in MOVE_PARTS)  # §66 按部位分开的动作票
ADD_CATEGORIES = (
    "supplement",
    "food",
    "move",
    "fat",
    "gain",
    "meal",
    "protein",
    "gear",
)  # 每天添加上限一起算
CARD_TOP = 5
SEARCH_TOP = 12
COMMENT_MAX = 200
DAILY_COMMENTS = 30
HOT_DAYS, HOT_TOP = 7, 8
TERM_MAX = 20
NICK_MIN, NICK_MAX = 2, 12

_BANNED = re.compile(
    r"加\s*微信|微信号|加\s*v|vx|qq\s*群|代购|返现|刷单|兼职|私聊|傻逼|傻b|草泥马|操你|去死|脑残|贱人",
    re.I,
)
_CONTACT = re.compile(r"\d{7,}|@[\w-]+\.\w+|https?://|www\.", re.I)
_CLAIMS = re.compile(r"治|疗效|根治|降血[压糖脂]|抗癌|药效|包好|保证瘦|排毒")
_NICK_A = (
    "练腿的",
    "早起的",
    "爱跑步的",
    "不挑食的",
    "下班就练的",
    "居家撸铁的",
    "刚入坑的",
    "坚持打卡的",
)
_NICK_B = ("小熊", "橙子", "海豹", "企鹅", "土豆", "柠檬", "松鼠", "鲸鱼")


@dataclass(frozen=True)
class Comment:
    id: str
    board: str
    key: str
    user_id: str  # 只在服务端用（删自己的、每天上限），不返回
    text: str
    created: datetime


class RankStore(Protocol):
    async def add_comment(self, c: Comment) -> None: ...
    async def comments(self, board: str) -> list[Comment]: ...
    async def comment(self, cid: str) -> Comment | None: ...
    async def delete_comment(self, cid: str) -> None: ...
    async def comments_since(self, user_id: str, since: datetime) -> int: ...
    async def like(self, cid: str, user_id: str, on: bool) -> None: ...
    async def likes(self, board: str) -> list[tuple[str, str]]: ...
    async def report_comment(self, cid: str, user_id: str) -> None: ...
    async def comment_reports(self, board: str) -> dict[str, int]: ...
    async def nicks(self, user_ids: list[str]) -> dict[str, str]: ...
    async def set_nick(self, user_id: str, nick: str) -> None: ...
    async def add_search(self, term: str, day: date) -> None: ...
    async def searches(self, since: date) -> list[tuple[str, date, int]]: ...
    async def snapshots(self, board: str) -> dict[str, dict[str, int]]: ...
    async def save_snapshot(self, board: str, week: date, ranks: dict[str, int]) -> None: ...


class RankBook:
    """内存版（测试用）。"""

    def __init__(self) -> None:
        self._comments: dict[str, Comment] = {}
        self._likes: set[tuple[str, str]] = set()
        self._reports: set[tuple[str, str]] = set()
        self._nicks: dict[str, str] = {}
        self._search: Counter[tuple[str, date]] = Counter()
        self._snaps: dict[tuple[str, str], dict[str, int]] = {}

    async def add_comment(self, c: Comment) -> None:
        self._comments[c.id] = c

    async def comments(self, board: str) -> list[Comment]:
        return [c for c in self._comments.values() if c.board == board]

    async def comment(self, cid: str) -> Comment | None:
        return self._comments.get(cid)

    async def delete_comment(self, cid: str) -> None:
        self._comments.pop(cid, None)
        self._likes = {x for x in self._likes if x[0] != cid}
        self._reports = {x for x in self._reports if x[0] != cid}

    async def comments_since(self, user_id: str, since: datetime) -> int:
        return sum(
            1 for c in self._comments.values() if c.user_id == user_id and c.created >= since
        )

    async def like(self, cid: str, user_id: str, on: bool) -> None:
        if on:
            self._likes.add((cid, user_id))
        else:
            self._likes.discard((cid, user_id))

    async def likes(self, board: str) -> list[tuple[str, str]]:
        ids = {c.id for c in await self.comments(board)}
        return [x for x in self._likes if x[0] in ids]

    async def report_comment(self, cid: str, user_id: str) -> None:
        self._reports.add((cid, user_id))

    async def comment_reports(self, board: str) -> dict[str, int]:
        ids = {c.id for c in await self.comments(board)}
        return dict(Counter(c for c, _ in self._reports if c in ids))

    async def nicks(self, user_ids: list[str]) -> dict[str, str]:
        return {u: self._nicks[u] for u in user_ids if u in self._nicks}

    async def set_nick(self, user_id: str, nick: str) -> None:
        self._nicks[user_id] = nick

    async def add_search(self, term: str, day: date) -> None:
        self._search[(term, day)] += 1

    async def searches(self, since: date) -> list[tuple[str, date, int]]:
        return [(t, d, n) for (t, d), n in self._search.items() if d >= since]

    async def snapshots(self, board: str) -> dict[str, dict[str, int]]:
        return {w: dict(r) for (b, w), r in self._snaps.items() if b == board}

    async def save_snapshot(self, board: str, week: date, ranks: dict[str, int]) -> None:
        self._snaps.setdefault((board, week.isoformat()), dict(ranks))


DDL = """
CREATE TABLE IF NOT EXISTS ironm_rank_comment (
    id         text PRIMARY KEY,
    board      text NOT NULL,
    key        text NOT NULL,
    user_id    text NOT NULL,
    text       text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ironm_rank_comment_board ON ironm_rank_comment (board);
CREATE TABLE IF NOT EXISTS ironm_rank_like (
    comment_id text NOT NULL,
    user_id    text NOT NULL,
    PRIMARY KEY (comment_id, user_id)
);
CREATE TABLE IF NOT EXISTS ironm_rank_comment_report (
    comment_id text NOT NULL,
    user_id    text NOT NULL,
    PRIMARY KEY (comment_id, user_id)
);
CREATE TABLE IF NOT EXISTS ironm_rank_nick (
    user_id text PRIMARY KEY,
    nick    text NOT NULL
);
CREATE TABLE IF NOT EXISTS ironm_rank_search (
    term text NOT NULL,
    day  date NOT NULL,
    n    integer NOT NULL DEFAULT 0,
    PRIMARY KEY (term, day)
);
CREATE TABLE IF NOT EXISTS ironm_rank_snapshot (
    board text NOT NULL,
    week  date NOT NULL,
    ranks jsonb NOT NULL,
    PRIMARY KEY (board, week)
)
"""


class PgRank:
    """数据库版：评论和昵称公开，不加密；搜索词只按天计数，不存账号。"""

    def __init__(self) -> None:
        self._ready = False

    async def _q(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        from mirobody.utils.db import execute_query

        if not self._ready:
            await run_ddl(*DDL.split(";"))
            self._ready = True
        rows = await execute_query(sql, params, log_sql=False)
        return rows if isinstance(rows, list) else []

    @staticmethod
    def _c(r: dict[str, Any]) -> Comment:
        return Comment(str(r["id"]), str(r["board"]), str(r["key"]), str(r["user_id"]),
                       str(r["text"]), r["created_at"])  # fmt: skip

    async def add_comment(self, c: Comment) -> None:
        await self._q(
            "INSERT INTO ironm_rank_comment (id, board, key, user_id, text)"
            " VALUES (:id, :board, :key, :uid, :text)",
            {"id": c.id, "board": c.board, "key": c.key, "uid": c.user_id, "text": c.text},
        )

    async def comments(self, board: str) -> list[Comment]:
        got = await self._q("SELECT * FROM ironm_rank_comment WHERE board = :b", {"b": board})
        return [self._c(r) for r in got]

    async def comment(self, cid: str) -> Comment | None:
        got = await self._q("SELECT * FROM ironm_rank_comment WHERE id = :id", {"id": cid})
        return self._c(got[0]) if got else None

    async def delete_comment(self, cid: str) -> None:
        for table, col in (("ironm_rank_like", "comment_id"), ("ironm_rank_comment_report", "comment_id"),
                           ("ironm_rank_comment", "id")):  # fmt: skip
            await self._q(f"DELETE FROM {table} WHERE {col} = :id", {"id": cid})

    async def comments_since(self, user_id: str, since: datetime) -> int:
        got = await self._q(
            "SELECT count(*) AS n FROM ironm_rank_comment WHERE user_id = :uid AND created_at >= :t",
            {"uid": user_id, "t": since},
        )
        return int(got[0]["n"]) if got else 0

    async def like(self, cid: str, user_id: str, on: bool) -> None:
        sql = (
            "INSERT INTO ironm_rank_like (comment_id, user_id) VALUES (:id, :uid) ON CONFLICT DO NOTHING"
            if on
            else "DELETE FROM ironm_rank_like WHERE comment_id = :id AND user_id = :uid"
        )
        await self._q(sql, {"id": cid, "uid": user_id})

    async def likes(self, board: str) -> list[tuple[str, str]]:
        got = await self._q(
            "SELECT l.comment_id, l.user_id FROM ironm_rank_like l JOIN ironm_rank_comment c"
            " ON c.id = l.comment_id WHERE c.board = :b",
            {"b": board},
        )
        return [(str(r["comment_id"]), str(r["user_id"])) for r in got]

    async def report_comment(self, cid: str, user_id: str) -> None:
        await self._q(
            "INSERT INTO ironm_rank_comment_report (comment_id, user_id) VALUES (:id, :uid)"
            " ON CONFLICT DO NOTHING",
            {"id": cid, "uid": user_id},
        )

    async def comment_reports(self, board: str) -> dict[str, int]:
        got = await self._q(
            "SELECT r.comment_id, count(*) AS n FROM ironm_rank_comment_report r JOIN ironm_rank_comment c"
            " ON c.id = r.comment_id WHERE c.board = :b GROUP BY r.comment_id",
            {"b": board},
        )
        return {str(r["comment_id"]): int(r["n"]) for r in got}

    async def nicks(self, user_ids: list[str]) -> dict[str, str]:
        if not user_ids:
            return {}
        got = await self._q(
            "SELECT user_id, nick FROM ironm_rank_nick WHERE user_id = ANY(:ids)", {"ids": user_ids}
        )
        return {str(r["user_id"]): str(r["nick"]) for r in got}

    async def set_nick(self, user_id: str, nick: str) -> None:
        await self._q(
            "INSERT INTO ironm_rank_nick (user_id, nick) VALUES (:uid, :nick)"
            " ON CONFLICT (user_id) DO UPDATE SET nick = EXCLUDED.nick",
            {"uid": user_id, "nick": nick},
        )

    async def add_search(self, term: str, day: date) -> None:
        await self._q(
            "INSERT INTO ironm_rank_search (term, day, n) VALUES (:t, :d, 1)"
            " ON CONFLICT (term, day) DO UPDATE SET n = ironm_rank_search.n + 1",
            {"t": term, "d": day},
        )

    async def searches(self, since: date) -> list[tuple[str, date, int]]:
        got = await self._q(
            "SELECT term, day, n FROM ironm_rank_search WHERE day >= :d", {"d": since}
        )
        return [(str(r["term"]), r["day"], int(r["n"])) for r in got]

    async def snapshots(self, board: str) -> dict[str, dict[str, int]]:
        got = await self._q(
            "SELECT week, ranks FROM ironm_rank_snapshot WHERE board = :b", {"b": board}
        )
        out = {}
        for r in got:
            ranks = r["ranks"] if isinstance(r["ranks"], dict) else json.loads(r["ranks"])
            out[r["week"].isoformat()] = {str(k): int(v) for k, v in ranks.items()}
        return out

    async def save_snapshot(self, board: str, week: date, ranks: dict[str, int]) -> None:
        await self._q(
            "INSERT INTO ironm_rank_snapshot (board, week, ranks) VALUES (:b, :w, CAST(:r AS jsonb))"
            " ON CONFLICT DO NOTHING",
            {"b": board, "w": week, "r": json.dumps(ranks, ensure_ascii=False)},
        )


_default: RankStore | None = None


def default_rank() -> RankStore:
    global _default
    if _default is None:
        _default = PgRank()
    return _default


# ---- 条目和投票 -------------------------------------------------------------------------------


def check_board(board: str) -> None:
    if board not in BOARD_NAMES:
        raise TierError("没有这个榜")


@dataclass(frozen=True)
class Seed:
    name: str
    desc: str = ""
    tag: str = ""


@cache
def _seeds() -> dict[str, tuple[Seed, ...]]:
    raw = yaml.safe_load((Path(__file__).with_name("rank_seed.yaml")).read_text()) or {}
    out: dict[str, tuple[Seed, ...]] = {}
    for b in BOARD_NAMES:
        rows = raw.get(b) or ()
        out[b] = tuple(
            Seed(str(x["name"]), str(x.get("desc") or ""), str(x.get("tag") or ""))
            if isinstance(x, dict)
            else Seed(str(x))
            for x in rows
        )
    return out


@dataclass(frozen=True)
class Entry:
    key: str
    name: str
    part: str = ""  # 动作库里的动作写部位；用户加的动作没有部位
    custom: bool = True  # 用户能举报的（起步条目和用户加的）；动作库、方案库里的不能
    added: str = ""  # 用户添加的时间（"新上榜"排序用）；起步条目和动作库的没有
    desc: str = ""  # 一句说明（§80）；用户加的没有
    tag: str = ""  # 标签：健身餐的减脂 / 增肌，训练计划的标准方案 / 博主方案


def boards_of(board: str) -> tuple[str, ...]:
    """这个榜和合并进来的旧榜（§80）。"""
    return (board, *MERGED.get(board, ()))


def _plans() -> list[Entry]:
    from ironm_agent.protools.templates import templates

    return [Entry(t.id, t.name, custom=False, desc=plan_blurb(t),
                  tag="标准方案" if t.standard else "博主方案" if t.kind == "blogger" else "")
            for t in templates()]  # fmt: skip


async def entries(tiers: TierStore, board: str) -> list[Entry]:
    """这个榜所有人能看到的条目。被 3 个人举报的不算。"""
    check_board(board)
    reports: Counter[str] = Counter()
    for b in boards_of(board):
        reports.update(await tiers.reports(b))
    hidden = {k for k, n in reports.items() if n >= HIDE_REPORTS}
    out: list[Entry] = []
    if board == "move":
        out = [Entry(x.id, x.name, x.part, False, desc=f"{x.part} · {x.muscles}")
               for x in library().exercises]  # fmt: skip
    elif board == "plan":
        out = _plans()
    seen = {e.key for e in out}
    for seed in _seeds()[board]:
        key = custom_key(seed.name)
        if key not in seen:
            out.append(Entry(key, seed.name, desc=seed.desc, tag=seed.tag))
            seen.add(key)
    for b in boards_of(board):
        for x in await tiers.items(b):
            if x.key not in seen:
                out.append(Entry(x.key, x.name, added=x.created.isoformat(timespec="seconds")))
                seen.add(x.key)
    return [e for e in out if e.key not in hidden]


async def board_votes(tiers: TierStore, board: str) -> list[Vote]:
    """这个榜的票；动作榜并上 §66 按部位分开的票、健身餐榜并上减脂餐和增肌餐榜的票（同一人同一条目以新榜的为准）。"""
    got = {(v.user_id, v.key): v for v in await tiers.votes(board)}
    for cat in (*(LEGACY_MOVES if board == "move" else ()), *MERGED.get(board, ())):
        for v in await tiers.votes(cat):
            got.setdefault((v.user_id, v.key), v)
    return [v for v in got.values() if v.tier in TIER_KEYS]


async def set_vote(tiers: TierStore, user_id: str, board: str, key: str, tier: str) -> None:
    """投票、改票；tier 为空串是撤回。动作榜同时清掉 §66 旧的那一票，免得撤回后旧票又出来。"""
    if tier and tier not in TIER_KEYS:
        raise TierError("没有这一档")
    found = next((e for e in await entries(tiers, board) if e.key == key), None)
    if found is None:
        raise TierError("没有这个条目")
    await tiers.vote(user_id, board, key, tier)
    if board == "move" and found.part in MOVE_PARTS:
        await tiers.vote(user_id, f"move:{found.part}", key, "")
    for old in MERGED.get(board, ()):  # 旧榜的那一票清掉，免得撤回后旧票又出来
        await tiers.vote(user_id, old, key, "")


async def add_entry(
    tiers: TierStore, user_id: str, board: str, name: str, today: date, force: bool = False
) -> dict[str, Any]:
    """添加条目：同名的直接用已有的；有相似的且没确认（force）时不新建，返回相似的；每人每天 10 个。"""
    if board in NO_ADD:
        raise TierError("训练计划榜的计划来自方案库，不能添加")
    text = clean_name(name)
    key = custom_key(text)
    have = await entries(tiers, board)
    same = next((e for e in have if norm(e.name) == norm(text) or e.key == key), None)
    if same is not None:
        return {"key": same.key, "similar": []}
    for b in boards_of(board):
        if any(x.key == key for x in await tiers.items(b)):
            raise TierError("这个条目被举报后隐藏了")
    now = datetime.now().astimezone()
    near = similar(text, [Item(board, e.key, e.name, "", now) for e in have])
    if near and not force:
        return {"key": None, "similar": [{"key": x.key, "name": x.name} for x in near]}
    mine = [x for c in ADD_CATEGORIES for x in await tiers.items(c) if x.added_by == user_id]
    if sum(1 for x in mine if x.created.date() == today) >= DAILY_ADDS:
        raise TierError(f"每天最多添加 {DAILY_ADDS} 个，明天再来")
    await tiers.add(Item(board, key, text, user_id, now))
    return {"key": key, "similar": []}


async def report_entry(tiers: TierStore, user_id: str, board: str, key: str) -> None:
    found = next((e for e in await entries(tiers, board) if e.key == key), None)
    if found is None:
        raise TierError("没有这个条目")
    if not found.custom:
        raise TierError("动作库里的动作、方案库里的计划不能举报")
    await tiers.report(user_id, board, key)


# ---- 排名、名次变化 ----------------------------------------------------------------------------


def week_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _rows(items: list[Entry], votes: list[Vote], user_id: str) -> list[dict[str, Any]]:
    by_key: dict[str, list[Vote]] = {}
    for v in votes:
        by_key.setdefault(v.key, []).append(v)
    rows: list[dict[str, Any]] = []
    for e in items:
        mine = by_key.get(e.key, [])
        counts = {t: sum(1 for v in mine if v.tier == t) for t, _ in TIERS}
        n = sum(counts.values())
        mean = sum(POINTS[t] * c for t, c in counts.items()) / n if n else 0.0
        rows.append({
            "key": e.key, "name": e.name, "part": e.part, "custom": e.custom, "added": e.added,
            "desc": e.desc, "tag": e.tag,
            "votes": n, "mean": round(mean, 1) if n else None,
            "score": round(shrunk(mean, n), 3) if n else None,
            "tier": tier_of(mean) if n >= MIN_VOTES else "",
            "counts": counts,
            "mine": next((v.tier for v in mine if v.user_id == user_id), ""),
            "rank": None, "trend": "",
        })  # fmt: skip
    rows.sort(key=lambda r: (-(r["score"] or 0), -r["votes"]))
    for i, r in enumerate(x for x in rows if x["votes"] >= MIN_VOTES):
        r["rank"] = i + 1
    return rows


def trends(rows: list[dict[str, Any]], snaps: dict[str, dict[str, int]], week: date) -> None:
    """和这周开头记下的名次比：↑2、↓1、新；这个榜第一周（之前没记过）不显示。"""
    base = snaps.get(week.isoformat())
    if base is None or not any(w < week.isoformat() for w in snaps):
        return
    for r in rows:
        if r["rank"] is None:
            continue
        was = base.get(r["key"])
        d = 0 if was is None else was - r["rank"]
        r["trend"] = "新" if was is None else f"↑{d}" if d > 0 else f"↓{-d}" if d < 0 else ""


async def ranked(
    tiers: TierStore, rank: RankStore, user_id: str, board: str, today: date, part: str = ""
) -> list[dict[str, Any]]:
    """一个榜的全部条目（上榜的在前，按名次）。这周第一次有人看时记下名次（近似周一零点）。
    按部位筛选时名次是部位内的，不显示名次变化。"""
    items = await entries(tiers, board)
    rows = _rows(items, await board_votes(tiers, board), user_id)
    week = week_of(today)
    snaps = await rank.snapshots(board)
    if week.isoformat() not in snaps:
        now = {r["key"]: r["rank"] for r in rows if r["rank"] is not None}
        await rank.save_snapshot(board, week, now)
        snaps[week.isoformat()] = now
    trends(rows, snaps, week)
    if part:
        rows = [dict(r, trend="", rank=None) for r in rows if r["part"] == part]
        for i, r in enumerate(x for x in rows if x["votes"] >= MIN_VOTES):
            r["rank"] = i + 1
    return rows


# ---- 评论 ------------------------------------------------------------------------------------


def random_nick() -> str:
    return secrets.choice(_NICK_A) + secrets.choice(_NICK_B)


def check_text(text: str, board: str = "") -> str:
    t = " ".join(str(text).split())
    if not t:
        raise TierError("先写点什么")
    if len(t) > COMMENT_MAX:
        raise TierError(f"最多 {COMMENT_MAX} 字")
    if _BANNED.search(t) or _CONTACT.search(t):
        raise TierError("有不合适的词或联系方式，没发出去")
    if board in NO_CLAIMS and _CLAIMS.search(t):
        raise TierError("补剂、蛋白粉的评论不写疗效，这条没发出去")
    return t


def check_nick(nick: str) -> str:
    t = "".join(str(nick).split())
    if not NICK_MIN <= len(t) <= NICK_MAX:
        raise TierError(f"昵称 {NICK_MIN} 到 {NICK_MAX} 个字")
    if _BANNED.search(t) or _CONTACT.search(t):
        raise TierError("昵称里有不合适的词")
    return t


async def my_nick(rank: RankStore, user_id: str, create: bool = False) -> str:
    got = (await rank.nicks([user_id])).get(user_id, "")
    if not got and create:
        got = random_nick()
        await rank.set_nick(user_id, got)
    return got


async def comment_rows(
    rank: RankStore, user_id: str, board: str
) -> dict[str, list[dict[str, Any]]]:
    """这个榜每个条目的评论（被 3 个人举报的不算），按点赞从多到少。只给昵称，不给账号。
    合并进来的旧榜（§80）的评论一起算。"""
    reports: Counter[str] = Counter()
    cs, likes = [], []
    for b in boards_of(board):
        reports.update(await rank.comment_reports(b))
        cs += await rank.comments(b)
        likes += await rank.likes(b)
    hidden = {c for c, n in reports.items() if n >= HIDE_REPORTS}
    cs = [c for c in cs if c.id not in hidden]
    count = Counter(c for c, _ in likes)
    liked = {c for c, u in likes if u == user_id}
    names = await rank.nicks(sorted({c.user_id for c in cs}))
    out: dict[str, list[dict[str, Any]]] = {}
    for c in cs:
        out.setdefault(c.key, []).append({
            "id": c.id, "nick": names.get(c.user_id, "健身的人"), "text": c.text,
            "likes": count[c.id], "liked": c.id in liked, "mine": c.user_id == user_id,
            "at": c.created.isoformat(timespec="seconds"),
        })  # fmt: skip
    for v in out.values():
        v.sort(key=lambda x: (x["likes"], x["at"]), reverse=True)  # 热门；同样多赞的新的在前
    return out


async def add_comment(
    tiers: TierStore, rank: RankStore, user_id: str, board: str, key: str, text: str
) -> None:
    body = check_text(text, board)
    if not any(e.key == key for e in await entries(tiers, board)):
        raise TierError("没有这个条目")
    now = datetime.now().astimezone()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if await rank.comments_since(user_id, start) >= DAILY_COMMENTS:
        raise TierError(f"每天最多发 {DAILY_COMMENTS} 条评论，明天再来")
    await my_nick(rank, user_id, create=True)
    await rank.add_comment(Comment(secrets.token_hex(8), board, key, user_id, body, now))


async def own_comment(rank: RankStore, user_id: str, cid: str, *, mine: bool) -> Comment:
    c = await rank.comment(cid)
    if c is None:
        raise TierError("没有这条评论")
    if mine and c.user_id != user_id:
        raise TierError("只能删自己的评论")
    return c


# ---- 搜索和热搜 --------------------------------------------------------------------------------


def clean_term(q: str) -> str:
    return " ".join(str(q).split())[:TERM_MAX]


async def search(tiers: TierStore, q: str) -> list[dict[str, Any]]:
    s = norm(clean_term(q))
    if not s:
        return []
    out = []
    for b in BOARD_NAMES:
        rows = _rows(await entries(tiers, b), await board_votes(tiers, b), "")
        out += [{"board": b, "board_name": BOARD_NAMES[b], "icon": BOARD_ICONS[b], "key": r["key"],
                 "name": r["name"], "tier": r["tier"], "mean": r["mean"], "votes": r["votes"]}
                for r in rows if s in norm(r["name"])]  # fmt: skip
    out.sort(key=lambda x: (-x["votes"], len(x["name"])))
    return out[:SEARCH_TOP]


async def record_search(rank: RankStore, q: str, hits: int, today: date) -> bool:
    """搜得到条目、没有敏感词的词才记（只按天计数，不记谁搜的）。"""
    term = clean_term(q)
    if not term or not hits or _BANNED.search(term) or _CONTACT.search(term):
        return False
    await rank.add_search(term, today)
    return True


async def hot(rank: RankStore, today: date) -> list[dict[str, str]]:
    """最近 7 天搜得最多的前 8 个。标签：前两名"热"；只在最近两天被搜的"新"；最近三天比前四天多的"升"。"""
    rows = await rank.searches(today - timedelta(days=HOT_DAYS - 1))
    total: Counter[str] = Counter()
    recent: Counter[str] = Counter()
    early: Counter[str] = Counter()
    for t, d, n in rows:
        total[t] += n
        (recent if (today - d).days < 3 else early)[t] += n
    out = []
    for i, (t, _) in enumerate(sorted(total.items(), key=lambda x: (-x[1], x[0]))[:HOT_TOP]):
        days = {(today - d).days for tt, d, _ in rows if tt == t}
        flag = (
            "热" if i < 2 else "新" if max(days) < 2 else "升" if recent[t] > early[t] > 0 else ""
        )
        out.append({"term": t, "flag": flag})
    return out


def disclaimer(board: str) -> str:
    return (
        "用户评价，不代表平台观点。补剂和蛋白粉只看评分，评论不写疗效。"
        if board in NO_CLAIMS
        else "用户评分，不代表平台观点。"
    )


def with_images(rows: list[dict[str, Any]], board: str = "move") -> None:
    """配图（§80）：动作用动作库的图；训练计划用它第一个动作的图；起步条目用 Commons 的图；用户加的没有。
    image 是地址，credit 是署名（作者、许可、来源）。"""
    for r in rows:
        r["image"], r["credit"] = None, None
        if board == "move" and not r["custom"]:
            imgs = images_for(r["key"])
            r["image"] = imgs[0]["url"] if imgs else None
        elif board == "plan":
            imgs = images_for(plan_cover(r["key"]))
            r["image"] = imgs[0]["url"] if imgs else None
        elif im := image_for(r["key"]):
            r["image"], r["credit"] = im["url"], im


# ---- 训练计划榜（§80）--------------------------------------------------------------------------

_REFS = re.compile(r"〔[^〕]*〕")
_LEVEL_SHORT = {"none": "零基础", "lt6m": "新手", "6m-2y": "有基础", "2y+": "练了多年"}


def _plain(text: str) -> str:
    """给人看的版本：去掉依据编号（追问时才说出处）。"""
    return _REFS.sub("", text)


def _template(key: str) -> Any:
    from ironm_agent.protools.templates import templates

    found = next((t for t in templates() if t.id == key), None)
    if found is None:
        raise TierError("没有这个计划")
    return found


def plan_blurb(t: Any) -> str:
    """一句话说清适合谁：人群或水平 · 目标 · 每周几天 · 场地。"""
    from ironm_agent.protools.templates import GOALS, PEOPLE, PLACES

    who = (
        PEOPLE[t.people[0]]
        if t.people[0] != "adult"
        else "各种水平"
        if len(t.levels) == len(_LEVEL_SHORT)
        else "、".join(dict.fromkeys(_LEVEL_SHORT[x] for x in t.levels))
    )
    ns = sorted(t.weeks)
    days = (
        f"{ns[0]}–{ns[-1]}"
        if len(ns) > 2 and ns[-1] - ns[0] == len(ns) - 1
        else "或".join(map(str, ns))
    )
    place = PLACES.get(t.place, "健身房或在家")
    return f"{who} · {'、'.join(GOALS[g] for g in t.goals[:2])} · 每周 {days} 天 · {place}"


def plan_cover(key: str) -> str:
    """训练计划的封面：第一次训练第一个动作在动作库里的编号。"""
    try:
        t = _template(key)
    except TierError:
        return ""
    first = next(iter(t.sessions.values()))[0]
    name = first.pick[0] if first.pick else ""
    return next((x.id for x in library().exercises if x.name == name), "")


def plan_detail(key: str) -> dict[str, Any]:
    """条目页上的计划（健身房版、按方案默认的天数）：每周怎么练、为什么、进阶、减量、来源。
    按他的情况改要进对话，由管家做（§77–79）。"""
    from ironm_agent.protools.templates import draft

    t = _template(key)
    days = 3 if 3 in t.weeks else min(t.weeks)
    plan, _ = draft(t, days, goal=t.goals[0], equipment=None)
    src = t.source
    return {
        "days": sorted(t.weeks),
        "sessions": [
            {
                "day": s.day,
                "name": s.name,
                "minutes": s.minutes,
                "items": [x.line() for x in s.items],
            }
            for s in plan.sessions
        ],
        "why": _plain(t.why),
        "intensity": _plain(t.intensity),
        "progress": _plain(t.progress),
        "deload": _plain(t.deload),
        "differs": [_plain(x) for x in t.conflicts],
        "source": None
        if src is None
        else {
            "authors": list(src.authors),
            "url": src.url,
            "secondhand": src.secondhand,
            "seen": src.seen.isoformat(),
        },
        "ask": f"我想用「{t.name}」这个训练计划，按我的情况改一下",
    }
