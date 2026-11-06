"""账号与隐私（spec [2026-10-23] §180）：导出我的数据、注销账号。

- 导出：IronM 自己的表（ironm_ 开头、有 user_id 列）里这个人的行，加密的内容解开，一个 JSON 文件；
  不含模型密钥（ironm_user_model）、照片和内部运行记录（ironm_turn_trace）。健康记录用 mirobody 自带的
  /api/user/data-export 另下。
- 注销：要输入本人邮箱确认；先删 IronM 表里这个人的所有行，再调 mirobody 自己的关账号（del_user，
  和它的 /user/del 一样：账号标成已删除、不能再登录）。mirobody 的代码一行不改（§168）。
- 表从数据库里现查（新加的表也跟着走）；日志只记表数和行数，不记内容。
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ironm_agent.web_password import _users

_log = logging.getLogger(__name__)
router = APIRouter()

NOT_EXPORTED = {
    "ironm_user_model": "模型密钥（安全起见不导出，在「我 → 模型和 API」里看得到末四位）",
    "ironm_turn_trace": "每轮问答的内部运行记录",
}
PHOTO_COLUMNS = frozenset({"photo", "photo_mime"})
ENCRYPTED = "gAAAA"  # encrypt_content 的前缀


def _verify() -> Any:
    from mirobody.server.auth import verify_token

    return verify_token


async def _query(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    from mirobody.utils.db import execute_query

    rows = await execute_query(sql, params, log_sql=False)
    return rows if isinstance(rows, list) else []


async def _tables() -> dict[str, list[tuple[str, str]]]:
    """IronM 里按人存的表：表名 → [(列名, 类型)]。"""
    rows = await _query(
        """
        SELECT c.table_name AS t, c.column_name AS c, c.data_type AS d
          FROM information_schema.columns c
         WHERE c.table_schema = current_schema()
           AND c.table_name LIKE 'ironm\\_%'
           AND c.table_name IN (SELECT table_name FROM information_schema.columns
                                 WHERE table_schema = current_schema() AND column_name = 'user_id')
         ORDER BY c.table_name, c.ordinal_position
        """,
        {},
    )
    out: dict[str, list[tuple[str, str]]] = {}
    for r in rows:
        out.setdefault(str(r["t"]), []).append((str(r["c"]), str(r["d"])))
    return out


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _plain(v: Any) -> Any:
    """解开后是 JSON 的转成对象，日期转成字符串。"""
    if isinstance(v, str) and v[:1] in "{[":
        try:
            return json.loads(v)
        except ValueError:
            return v
    if isinstance(v, datetime) or hasattr(v, "isoformat"):
        return v.isoformat()
    return v


@router.get("/iron/api/export")
async def export_mine(user_id: str = Depends(_verify())) -> JSONResponse:
    """本人在 IronM 里的数据，下载成一个 JSON 文件。"""
    tables = await _tables()
    data: dict[str, list[dict[str, Any]]] = {}
    for t, cols in tables.items():
        if t in NOT_EXPORTED:
            continue
        picks = []
        for c, d in cols:
            if c in PHOTO_COLUMNS:
                continue
            col = _q(c)
            picks.append(
                f"CASE WHEN {col} LIKE '{ENCRYPTED}%' THEN decrypt_content({col}) ELSE {col} END AS {col}"
                if d == "text"
                else col
            )
        rows = await _query(
            f"SELECT {', '.join(picks)} FROM {_q(t)} WHERE user_id = :uid", {"uid": user_id}
        )
        if rows:
            data[t.removeprefix("ironm_")] = [{k: _plain(v) for k, v in r.items()} for r in rows]
    now = datetime.now(UTC)
    body = {
        "exported_at": now.isoformat(),
        "about": "IronM 里你的数据：档案、计划、训练、饮食、目标、记忆、器材场所、排行榜里你写的评论和投票等。",
        "not_included": [*NOT_EXPORTED.values(), "照片（记一餐、打卡、体态的照片）"],
        "health_records": "体重等身体读数、化验、手表等健康记录在「我 → 账号与隐私」里另一个下载（mirobody 的 /api/user/data-export）",
        "data": data,
    }
    _log.info("export: tables=%d rows=%d", len(data), sum(len(v) for v in data.values()))
    return JSONResponse(
        body, headers={"Content-Disposition": f'attachment; filename="ironm-{now:%Y-%m-%d}.json"'}
    )


class DeleteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: str = Field(max_length=320)


@router.post("/iron/api/account/delete")
async def delete_account(
    body: DeleteIn, request: Request, user_id: str = Depends(_verify())
) -> dict[str, Any]:
    """注销：邮箱对上才删；先删 IronM 里本人的行，再关 mirobody 账号。"""
    from mirobody.user.user import del_user, get_user

    row = await get_user(user_id=int(user_id))
    email = str((row or {}).get("email") or "").strip().lower()
    if not email or body.confirm.strip().lower() != email:
        raise HTTPException(422, "邮箱和这个账号的不一样，没有注销")
    svc = _users(request)
    if svc is None:
        raise HTTPException(503, "账号服务暂时不可用，没有注销，稍后再试")
    tables = await _tables()
    n = 0
    for t in tables:
        n += len(
            await _query(f"DELETE FROM {_q(t)} WHERE user_id = :uid RETURNING 1", {"uid": user_id})
        )
    err = await del_user(svc._db_pool, int(user_id))
    _log.info("account delete: tables=%d rows=%d closed=%s", len(tables), n, err is None)
    if err:
        raise HTTPException(500, "IronM 里的数据已经删了，但账号没关成，再点一次注销")
    return {"ok": True, "deleted_rows": n}
