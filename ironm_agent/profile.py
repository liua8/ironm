"""个人中心的档案：身高、出生日期、性别、目标、活动水平。

存在同一个数据库里 iron-m 自己的表（不改 mirobody 的表）；没填的性别、出生日期从 mirobody 的账户里带出。
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from ironm_agent.metrics import ACTIVITY, GOALS, Activity, Goal, Profile, Sex

_log = logging.getLogger("ironm_agent.profile")

DDL = """
CREATE TABLE IF NOT EXISTS ironm_profile (
    user_id    text PRIMARY KEY,
    height_cm  double precision,
    birth      date,
    sex        text,
    goal       text,
    activity   text,
    updated_at timestamptz NOT NULL DEFAULT now()
)
"""

_ready = False


class ProfileIn(BaseModel):
    """页面提交的档案；没给的字段保持原样。"""

    model_config = ConfigDict(extra="forbid")

    height_cm: float | None = Field(default=None, ge=100, le=250)
    birth: date | None = None
    sex: Literal["male", "female"] | None = None
    goal: Literal["muscle", "strength", "fat_loss", "endurance", "health"] | None = None
    activity: Literal["sedentary", "light", "moderate", "active", "very_active"] | None = None


async def _q(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    from mirobody.utils.db import execute_query

    rows = await execute_query(sql, params or {}, log_sql=False)
    return rows if isinstance(rows, list) else []


async def _ensure() -> None:
    global _ready
    if not _ready:
        await _q(DDL)
        _ready = True


def _sex(v: Any) -> Sex | None:
    return "male" if v == "male" else "female" if v == "female" else None


def _goal(v: Any) -> Goal | None:
    return cast(Goal, v) if v in GOALS else None


def _activity(v: Any) -> Activity | None:
    return cast(Activity, v) if v in ACTIVITY else None


def _parse_birth(raw: Any) -> date | None:
    text = str(raw or "").strip()[:10]
    try:
        return date.fromisoformat(text) if len(text) == 10 else None
    except ValueError:
        return None


async def load(user_id: str) -> tuple[Profile, dict[str, str]]:
    """档案与每项的来源（档案 / 账户 / 空）。"""
    await _ensure()
    rows = await _q("SELECT * FROM ironm_profile WHERE user_id = :uid", {"uid": user_id})
    row = rows[0] if rows else {}
    account: dict[str, Any] = {}
    if user_id.isdigit():
        found = await _q(
            "SELECT gender, birth FROM health_app_user WHERE id = :id", {"id": int(user_id)}
        )
        account = found[0] if found else {}
    sex = _sex(row.get("sex")) or {1: "male", 2: "female"}.get(account.get("gender") or 0)
    birth = row.get("birth") or _parse_birth(account.get("birth"))
    sources = {
        "height_cm": "档案" if row.get("height_cm") else "",
        "birth": "档案" if row.get("birth") else ("账户" if birth else ""),
        "sex": "档案" if row.get("sex") else ("账户" if sex else ""),
        "goal": "档案" if row.get("goal") else "",
        "activity": "档案" if row.get("activity") else "",
    }
    profile = Profile(
        height_cm=row.get("height_cm"),
        birth=birth if isinstance(birth, date) else None,
        sex=_sex(sex),
        goal=_goal(row.get("goal")),
        activity=_activity(row.get("activity")),
    )
    return profile, sources


async def set_goal(user_id: str, goal: str | None) -> None:
    """只改目标类型（改目标的卡片确认或撤销时，§151）；None 是恢复成没填。"""
    await _ensure()
    await _q(
        "INSERT INTO ironm_profile (user_id, goal) VALUES (:uid, :goal)"
        " ON CONFLICT (user_id) DO UPDATE SET goal = EXCLUDED.goal, updated_at = now()",
        {"uid": user_id, "goal": goal},
    )


async def save(user_id: str, data: ProfileIn) -> None:
    await _ensure()
    fields = data.model_dump(exclude_unset=True)
    params = {
        "uid": user_id,
        **{k: fields.get(k) for k in ("height_cm", "birth", "sex", "goal", "activity")},
    }
    sets = (
        ", ".join(f"{k} = COALESCE(EXCLUDED.{k}, ironm_profile.{k})" for k in fields)
        or "user_id = EXCLUDED.user_id"
    )
    await _q(
        "INSERT INTO ironm_profile (user_id, height_cm, birth, sex, goal, activity) "
        "VALUES (:uid, :height_cm, :birth, :sex, :goal, :activity) "
        f"ON CONFLICT (user_id) DO UPDATE SET {sets}, updated_at = now()",
        params,
    )
