"""夯榜（排行榜）的接口（spec [2026-10-23] §72、§80）：首页（六个榜的前 5 和热搜）、榜单、条目详情
（训练计划带每周怎么练）、投票、添加、举报、搜索、评论（发、删自己的、点赞、举报）、昵称、起步条目的配图。

返回里没有投票人、添加人、评论人的账号（评论只带昵称）；日志只写榜和条数，不写评论内容和搜索词。
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from ironm_agent.rank import (
    BOARD_ICONS,
    BOARD_NAMES,
    BOARDS,
    CARD_TOP,
    COMMENT_MAX,
    NO_ADD,
    NO_CLAIMS,
    RankStore,
    add_comment,
    add_entry,
    board_votes,
    check_board,
    check_nick,
    comment_rows,
    default_rank,
    disclaimer,
    hot,
    my_nick,
    own_comment,
    plan_detail,
    ranked,
    record_search,
    report_entry,
    search,
    set_vote,
    with_images,
)
from ironm_agent.tier import HIDE_REPORTS, MIN_VOTES, TIERS, TierError, TierStore
from ironm_agent.web_more import _verify
from ironm_agent.web_tier import TIER

_log = logging.getLogger("ironm_agent.rank")


def rank_store() -> RankStore:
    return default_rank()


RANK = Depends(rank_store)  # 测试时用 dependency_overrides 换成内存版
router = APIRouter()


class VoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    board: str = Field(max_length=20)
    key: str = Field(max_length=80)
    tier: str = Field(default="", max_length=10)


class EntryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    board: str = Field(max_length=20)
    name: str = Field(max_length=200)
    force: bool = False  # 有相似的条目时，确认"不是这些"再新建


class KeyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    board: str = Field(max_length=20)
    key: str = Field(max_length=80)


class CommentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    board: str = Field(max_length=20)
    key: str = Field(max_length=80)
    text: str = Field(max_length=COMMENT_MAX * 2)


class LikeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    on: bool = True


class NickIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nick: str = Field(max_length=40)


def _bad(err: TierError) -> HTTPException:
    return HTTPException(422, str(err))


def _meta() -> dict[str, Any]:
    return {"tiers": [{"key": k, "name": n} for k, n in TIERS], "min_votes": MIN_VOTES,
            "hide_reports": HIDE_REPORTS, "comment_max": COMMENT_MAX}  # fmt: skip


async def _board(
    tiers: TierStore, rank: RankStore, user_id: str, board: str, part: str = ""
) -> dict[str, Any]:
    rows = await ranked(tiers, rank, user_id, board, date.today(), part)
    talk = await comment_rows(rank, user_id, board)
    for r in rows:
        cs = talk.get(r["key"], [])
        r["comments"] = len(cs)
        r["top_comment"] = cs[0] if cs else None
    with_images(rows, board)
    parts = sorted({r["part"] for r in rows if r["part"]}) if board == "move" and not part else []
    return {"board": board, "name": BOARD_NAMES[board], "icon": BOARD_ICONS[board], "part": part,
            "parts": parts, "items": rows, "people": len({v.user_id for v in await board_votes(tiers, board)}),
            "disclaimer": disclaimer(board), "no_claims": board in NO_CLAIMS,
            "can_add": board not in NO_ADD} | _meta()  # fmt: skip


async def _item(
    tiers: TierStore, rank: RankStore, user_id: str, board: str, key: str
) -> dict[str, Any]:
    rows = await ranked(tiers, rank, user_id, board, date.today())
    row = next((r for r in rows if r["key"] == key), None)
    if row is None:
        raise TierError("没有这个条目")
    with_images([row], board)
    comments = (await comment_rows(rank, user_id, board)).get(key, [])
    return {"board": board, "name": BOARD_NAMES[board], "item": row, "comments": comments,
            "nick": await my_nick(rank, user_id), "disclaimer": disclaimer(board),
            "no_claims": board in NO_CLAIMS,
            "plan": plan_detail(key) if board == "plan" else None} | _meta()  # fmt: skip


@router.get("/iron/api/rank")
async def get_home(
    user_id: str = Depends(_verify()), tiers: TierStore = TIER, rank: RankStore = RANK
) -> dict[str, Any]:
    """首页：每个榜的前 5（第一名带点赞最多的一条评论）、热搜（§80 起不再给下面的全部榜单）。"""
    cards = []
    for board, name, ic in BOARDS:
        got = await _board(tiers, rank, user_id, board)
        top = [r for r in got["items"] if r["rank"] is not None][:CARD_TOP]
        rest = sorted((r for r in got["items"] if r["rank"] is None), key=lambda r: -r["votes"])
        cards.append({"board": board, "name": name, "icon": ic, "people": got["people"], "top": top,
                      "fill": rest[: CARD_TOP - len(top)],  # 上榜的不到 5 个时，用待评的补上（开榜时都没票）
                      "waiting": len(rest)})  # fmt: skip
    return {"boards": cards, "hot": await hot(rank, date.today())} | _meta()


@router.get("/iron/api/rank/board")
async def get_board(
    board: str,
    part: str = "",
    user_id: str = Depends(_verify()),
    tiers: TierStore = TIER,
    rank: RankStore = RANK,
) -> dict[str, Any]:
    try:
        check_board(board)
        if part and board != "move":
            raise TierError("只有动作榜能按部位看")
        return await _board(tiers, rank, user_id, board, part[:10])
    except TierError as err:
        raise _bad(err) from None


@router.get("/iron/api/rank/item")
async def get_item(
    board: str,
    key: str,
    user_id: str = Depends(_verify()),
    tiers: TierStore = TIER,
    rank: RankStore = RANK,
) -> dict[str, Any]:
    try:
        check_board(board)
        return await _item(tiers, rank, user_id, board, key)
    except TierError as err:
        raise _bad(err) from None


@router.put("/iron/api/rank/vote")
async def put_vote(
    body: VoteIn, user_id: str = Depends(_verify()), tiers: TierStore = TIER, rank: RankStore = RANK
) -> dict[str, Any]:
    try:
        check_board(body.board)
        await set_vote(tiers, user_id, body.board, body.key, body.tier)
        return await _item(tiers, rank, user_id, body.board, body.key)
    except TierError as err:
        raise _bad(err) from None


@router.post("/iron/api/rank/items")
async def post_entry(
    body: EntryIn, user_id: str = Depends(_verify()), tiers: TierStore = TIER
) -> dict[str, Any]:
    try:
        check_board(body.board)
        got = await add_entry(tiers, user_id, body.board, body.name, date.today(), body.force)
        _log.info("rank entry added: board=%s similar=%d", body.board, len(got["similar"]))
        return got
    except TierError as err:
        raise _bad(err) from None


@router.post("/iron/api/rank/report")
async def post_report(
    body: KeyIn, user_id: str = Depends(_verify()), tiers: TierStore = TIER
) -> dict[str, Any]:
    try:
        check_board(body.board)
        await report_entry(tiers, user_id, body.board, body.key)
        _log.info("rank entry reported: board=%s", body.board)
        return {"ok": True}
    except TierError as err:
        raise _bad(err) from None


@router.get("/iron/api/rank/search")
async def get_search(
    q: str,
    record: bool = True,
    user_id: str = Depends(_verify()),
    tiers: TierStore = TIER,
    rank: RankStore = RANK,
) -> dict[str, Any]:
    """搜所有榜的条目；搜得到的词记进热搜（只按天计数，不记谁搜的）。
    边打字边搜时 record=false，按回车、点热搜或点结果才记，免得打到一半的字进热搜。"""
    hits = await search(tiers, q)
    if record:
        await record_search(rank, q, len(hits), date.today())
    _log.info("rank search: hits=%d", len(hits))
    return {"items": hits}


@router.post("/iron/api/rank/comments")
async def post_comment(
    body: CommentIn,
    user_id: str = Depends(_verify()),
    tiers: TierStore = TIER,
    rank: RankStore = RANK,
) -> dict[str, Any]:
    try:
        check_board(body.board)
        await add_comment(tiers, rank, user_id, body.board, body.key, body.text)
        _log.info("rank comment added: board=%s", body.board)
        return await _item(tiers, rank, user_id, body.board, body.key)
    except TierError as err:
        raise _bad(err) from None


@router.delete("/iron/api/rank/comments/{cid}")
async def delete_comment(
    cid: str, user_id: str = Depends(_verify()), rank: RankStore = RANK
) -> dict[str, Any]:
    try:
        c = await own_comment(rank, user_id, cid[:40], mine=True)
        await rank.delete_comment(c.id)
        return {"ok": True}
    except TierError as err:
        raise _bad(err) from None


@router.post("/iron/api/rank/comments/{cid}/like")
async def like_comment(
    cid: str, body: LikeIn, user_id: str = Depends(_verify()), rank: RankStore = RANK
) -> dict[str, Any]:
    try:
        c = await own_comment(rank, user_id, cid[:40], mine=False)
        await rank.like(c.id, user_id, body.on)
        return {"ok": True}
    except TierError as err:
        raise _bad(err) from None


@router.post("/iron/api/rank/comments/{cid}/report")
async def report_comment(
    cid: str, user_id: str = Depends(_verify()), rank: RankStore = RANK
) -> dict[str, Any]:
    try:
        c = await own_comment(rank, user_id, cid[:40], mine=False)
        await rank.report_comment(c.id, user_id)
        _log.info("rank comment reported: board=%s", c.board)
        return {"ok": True}
    except TierError as err:
        raise _bad(err) from None


@router.get("/iron/api/rank/nick")
async def get_nick(user_id: str = Depends(_verify()), rank: RankStore = RANK) -> dict[str, str]:
    return {"nick": await my_nick(rank, user_id, create=True)}


@router.put("/iron/api/rank/nick")
async def put_nick(
    body: NickIn, user_id: str = Depends(_verify()), rank: RankStore = RANK
) -> dict[str, str]:
    try:
        nick = check_nick(body.nick)
        await rank.set_nick(user_id, nick)
        return {"nick": nick}
    except TierError as err:
        raise _bad(err) from None


@router.get("/iron/api/rank-images/{name}")
async def get_rank_image(name: str) -> FileResponse:
    """起步条目的配图（§80）：公开内容（来自 Wikimedia Commons，许可允许再用），<img> 带不了登录凭证，不验证登录。"""
    from ironm_agent.rank_images import image_path

    p = image_path(name)
    if p is None:
        raise HTTPException(404, "没有这张图")
    return FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})
