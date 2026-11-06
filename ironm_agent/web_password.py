"""找回密码（spec [2026-11-03] §155；[2026-11-05] §168 从 mirobody 挪进 iron-m）。

邮箱验证码核对通过后重设密码。原来写在 mirobody 的 user_service 里；为了"并入 mirobody 不改它的逻辑"，
挪到 iron-m 自己的路由：路径照旧是 /password/reset（App 和网页不用改），用的仍是 mirobody 运行中的
用户服务（发验证码、核对验证码、签发登录凭证），只是不再往它的代码里加东西。

mirobody 没有直接给出用户服务对象，但把它的 requires_second_factor 方法放在了 app.state 上，
这里顺着这个方法取到对象本身；取不到（mirobody 换了写法）时如实回"没配发信"，不重设任何密码。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

_log = logging.getLogger(__name__)
router = APIRouter()

MIN_PASSWORD_LEN = 8  # 同 mirobody UserService._MIN_PASSWORD_LEN


def _users(request: Request) -> Any:
    """运行中的 mirobody 用户服务（见模块说明）；取不到返回 None。"""
    bound = getattr(request.app.state, "requires_second_factor", None)
    return getattr(bound, "__self__", None)


def _reply(code: int, msg: str, request: Request) -> Response:
    """mirobody 的回包格式 {code, msg, data}（和它的登录、注册接口一样，页面照旧解析）。"""
    from mirobody.utils import json_response_with_code

    resp: Response = json_response_with_code(code, msg, request=request)
    return resp


async def _query(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    from mirobody.utils import execute_query

    rows = await execute_query(sql, params, log_sql=False)
    return list(rows or [])


@router.post("/password/reset")
async def password_reset(request: Request) -> Response:
    """用邮箱验证码证明是本人，重设密码，成功后直接登录（回包和 mirobody 的密码登录一样）。

    验证码就是凭证，所以必须能发信：没配发信（演示用的假校验）时什么都不改。
    "没有这个账号"和"验证码不对"回同一句，不透露账号是否存在。"""
    from mirobody.user.user_service import UserService

    try:
        data = await request.json()
    except Exception:
        data = None
    if not isinstance(data, dict):
        return _reply(-1, "The request body must be a JSON object.", request)
    email, password = UserService._read_credentials(data)
    code = str(data.get("code") or "")
    if not email or "@" not in email or not code:
        return _reply(-2, "Email and code are required.", request)
    if len(password) < MIN_PASSWORD_LEN:
        return _reply(-3, f"Password must be at least {MIN_PASSWORD_LEN} characters.", request)
    svc = _users(request)
    if svc is None or not svc.sends_mail():
        return _reply(-7, "No mail sender is configured.", request)
    err = await svc._email_validator.verify(email, code)
    if err:
        return _reply(-6, err, request)
    rows = await _query(
        """
        UPDATE health_app_user
           SET password_hash = crypt(:password, gen_salt('bf', 12)),
               email_verified_at = COALESCE(email_verified_at, now())
         WHERE email = :email AND is_del = FALSE
        RETURNING id
        """,
        {"email": email, "password": password},
    )
    if not rows:
        return _reply(-6, "Incorrect email or code.", request)
    _log.info("password reset")
    resp: Response = await svc._generate_auth_response(rows[0]["id"], email, "password", request)
    return resp


# ---- 登录后设密码、改密码（spec [2026-11-05] §174）----
# 以前用验证码建的账号没有密码；mirobody 的注册不碰已有账号，找回密码要能发信。
# 登录后在「我」里设一个（没有密码时直接设，有了要先输旧密码），以后就用账号密码登录。


def _verify() -> Any:
    from mirobody.server.auth import verify_token

    return verify_token


class PasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(max_length=200)
    current: str = Field(default="", max_length=200)


@router.get("/iron/api/auth/password")
async def password_state(user_id: str = Depends(_verify())) -> dict[str, Any]:
    """这个账号有没有密码（「我」里显示"设密码"还是"改密码"）。"""
    rows = await _query(
        "SELECT password_hash IS NOT NULL AS has FROM health_app_user WHERE id = :id AND is_del = FALSE",
        {"id": int(user_id)},
    )
    return {"has_password": bool(rows and rows[0].get("has"))}


@router.put("/iron/api/auth/password")
async def set_password(body: PasswordIn, user_id: str = Depends(_verify())) -> dict[str, Any]:
    """设密码或改密码：已经有密码的要先输对旧密码；密码交给数据库用 bcrypt 算，日志不记。"""
    if len(body.password) < MIN_PASSWORD_LEN:
        raise HTTPException(422, f"密码至少 {MIN_PASSWORD_LEN} 位")
    rows = await _query(
        """
        SELECT password_hash IS NOT NULL AS has,
               (password_hash IS NOT NULL AND password_hash = crypt(:current, password_hash)) AS ok
          FROM health_app_user WHERE id = :id AND is_del = FALSE
        """,
        {"id": int(user_id), "current": body.current},
    )
    if not rows:
        raise HTTPException(404, "没有这个账号")
    if rows[0].get("has") and not rows[0].get("ok"):
        raise HTTPException(422, "原来的密码不对")
    await _query(
        "UPDATE health_app_user SET password_hash = crypt(:password, gen_salt('bf', 12)) "
        "WHERE id = :id AND is_del = FALSE RETURNING id",
        {"id": int(user_id), "password": body.password},
    )
    _log.info("password set: had=%s", bool(rows[0].get("has")))
    return {"has_password": True}
